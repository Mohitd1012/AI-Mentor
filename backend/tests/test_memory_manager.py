"""
Tests for Phase 7 — Memory System.

All tests use temp dirs so they don't touch the real DB / vector store.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from modules.memory_manager import MemoryManager, Memory, MemoryKind
from modules.memory_manager.sqlite_store import SQLiteStore
from modules.memory_manager.vector_store import VectorStore
from modules.memory_manager import extractor


@pytest.fixture
def tmp_mem(tmp_path: Path):
    return MemoryManager(
        sqlite_path=tmp_path / "test.db",
        chroma_dir=tmp_path / "chroma",
        extraction_enabled=False,
    )


# ── SQLite store ──────────────────────────────────────────────────────────────

class TestSQLiteStore:
    def test_add_and_recent_turns(self, tmp_path):
        from modules.memory_manager.models import ConversationTurn
        store = SQLiteStore(tmp_path / "x.db")
        for i in range(3):
            store.add_turn(ConversationTurn(
                session_id="s1", role="user", content=f"msg {i}",
            ))
        turns = store.recent_turns("s1", limit=10)
        assert len(turns) == 3
        assert turns[0].content == "msg 0"   # chronological

    def test_upsert_memory_and_list(self, tmp_path):
        store = SQLiteStore(tmp_path / "x.db")
        m = Memory(content="user likes Python", kind=MemoryKind.PREFERENCE, source="user")
        store.upsert_memory(m)
        all_mems = store.list_memories()
        assert len(all_mems) == 1
        assert all_mems[0].content == "user likes Python"

    def test_disable_memory(self, tmp_path):
        store = SQLiteStore(tmp_path / "x.db")
        m = Memory(content="x", kind=MemoryKind.NOTE)
        store.upsert_memory(m)
        store.set_enabled(m.id, False)
        enabled = store.list_memories(enabled_only=True)
        assert enabled == []

    def test_delete_memory(self, tmp_path):
        store = SQLiteStore(tmp_path / "x.db")
        m = Memory(content="x", kind=MemoryKind.NOTE)
        store.upsert_memory(m)
        assert store.delete_memory(m.id) is True
        assert store.get_memory(m.id) is None


# ── Vector store ──────────────────────────────────────────────────────────────

class TestVectorStore:
    def test_upsert_and_search(self, tmp_path):
        store = VectorStore(tmp_path / "chroma")
        store.upsert("a", "I love Python programming")
        store.upsert("b", "Kubernetes deployments and pods")
        store.upsert("c", "Trading on momentum strategies")

        hits = store.search("snake language coding", n_results=2)
        ids = [h["id"] for h in hits]
        assert "a" in ids   # Python should be closest match

    def test_delete(self, tmp_path):
        store = VectorStore(tmp_path / "chroma")
        store.upsert("a", "first memory")
        store.delete("a")
        hits = store.search("first", n_results=3)
        assert all(h["id"] != "a" for h in hits)

    def test_empty_query_returns_empty(self, tmp_path):
        store = VectorStore(tmp_path / "chroma")
        assert store.search("", n_results=3) == []


# ── MemoryManager — recall + persistence ──────────────────────────────────────

class TestMemoryManagerRecall:
    def test_recall_returns_relevant_block(self, tmp_mem):
        tmp_mem.add_memory("User is a Python developer who prefers concise answers",
                           kind=MemoryKind.PREFERENCE)
        tmp_mem.add_memory("User works at a startup building AI tools",
                           kind=MemoryKind.PROJECT)
        tmp_mem.add_memory("User enjoys mountain biking on weekends",
                           kind=MemoryKind.FACT)

        block = tmp_mem.recall("Tell me about Python decorators")
        assert "[RELEVANT MEMORY]" in block
        assert "Python" in block

    def test_recall_empty_query_returns_empty(self, tmp_mem):
        block = tmp_mem.recall("")
        assert block == ""

    def test_recall_excludes_disabled(self, tmp_mem):
        m = tmp_mem.add_memory("User loves Python", kind=MemoryKind.PREFERENCE)
        tmp_mem.update_memory(m.id, enabled=False)
        block = tmp_mem.recall("Python decorators")
        # Either no block at all, or the disabled memory isn't in it
        assert "User loves Python" not in block

    def test_recall_respects_k_limit(self, tmp_mem):
        for i in range(10):
            tmp_mem.add_memory(f"random fact about Python topic {i}",
                               kind=MemoryKind.NOTE)
        block = tmp_mem.recall("Python", k=2)
        # Block should have header + 2 lines + footer = ~4 lines
        assert block.count("•") == 2

    def test_save_user_turn_persists(self, tmp_mem):
        tmp_mem.save_user_turn("s1", "hello", role_id="default")
        turns = tmp_mem.recent_turns("s1")
        assert len(turns) == 1
        assert turns[0].content == "hello"


# ── CRUD ──────────────────────────────────────────────────────────────────────

class TestMemoryCRUD:
    def test_add_memory(self, tmp_mem):
        m = tmp_mem.add_memory("User prefers vim",
                                kind=MemoryKind.PREFERENCE)
        assert m.id is not None
        assert m.source == "user"
        assert tmp_mem.list_memories()[0].content == "User prefers vim"

    def test_update_content(self, tmp_mem):
        m = tmp_mem.add_memory("old content")
        updated = tmp_mem.update_memory(m.id, content="new content")
        assert updated.content == "new content"

    def test_update_disables(self, tmp_mem):
        m = tmp_mem.add_memory("x")
        tmp_mem.update_memory(m.id, enabled=False)
        assert tmp_mem.list_memories(enabled_only=True) == []

    def test_delete_returns_true(self, tmp_mem):
        m = tmp_mem.add_memory("doomed")
        assert tmp_mem.delete_memory(m.id) is True
        assert tmp_mem.list_memories() == []

    def test_delete_missing_returns_false(self, tmp_mem):
        assert tmp_mem.delete_memory("no-such-id") is False

    def test_clear_all(self, tmp_mem):
        for i in range(5):
            tmp_mem.add_memory(f"memory {i}")
        n = tmp_mem.clear_all()
        assert n == 5
        assert tmp_mem.list_memories() == []

    def test_extraction_toggle(self, tmp_mem):
        tmp_mem.set_extraction_enabled(False)
        assert tmp_mem.extraction_enabled is False
        tmp_mem.set_extraction_enabled(True)
        assert tmp_mem.extraction_enabled is True


# ── Extractor JSON parsing ────────────────────────────────────────────────────

class TestExtractorParsing:
    def test_clean_array(self):
        raw = '[{"kind":"preference","content":"User likes Python"}]'
        mems = extractor._parse_memories(raw, role_id="x")
        assert len(mems) == 1
        assert mems[0].kind == MemoryKind.PREFERENCE
        assert mems[0].role_id == "x"

    def test_wrapped_in_prose(self):
        raw = 'Here it is: [{"kind":"goal","content":"Learn rust"}] done.'
        mems = extractor._parse_memories(raw, role_id=None)
        assert len(mems) == 1
        assert mems[0].kind == MemoryKind.GOAL

    def test_empty_array(self):
        assert extractor._parse_memories("[]", None) == []

    def test_malformed_json_returns_empty(self):
        assert extractor._parse_memories("not json", None) == []

    def test_unknown_kind_falls_back_to_note(self):
        raw = '[{"kind":"weird","content":"something"}]'
        mems = extractor._parse_memories(raw, None)
        assert mems[0].kind == MemoryKind.NOTE

    def test_too_short_content_skipped(self):
        raw = '[{"kind":"note","content":"hi"}]'
        assert extractor._parse_memories(raw, None) == []

    def test_caps_at_three(self):
        items = [{"kind": "note", "content": f"item number {i}"} for i in range(10)]
        import json as _json
        raw = _json.dumps(items)
        mems = extractor._parse_memories(raw, None)
        assert len(mems) == 3


# ── Orchestrator integration (no live LLM) ────────────────────────────────────

class TestOrchestratorMemoryIntegration:
    @pytest.mark.asyncio
    async def test_handle_message_persists_turn(self, tmp_mem):
        from modules.ai_router.router import AIRouter
        from modules.react_planner import ConversationOrchestrator
        from modules.react_planner.models import Action, PlannerDecision

        router = AIRouter()
        orch = ConversationOrchestrator(router, memory=tmp_mem)

        async def fake_decide(self, ctx):
            return PlannerDecision(action=Action.TEACH, reasoning="test")

        async def fake_stream(self, msg, model_override=None, provider_override=None):
            yield "Hello there."

        with patch("modules.react_planner.planner.ReActPlanner.decide", fake_decide):
            with patch("modules.ai_router.router.AIRouter.stream_response", fake_stream):
                async for _ in orch.handle_message("what is x"):
                    pass

        turns = tmp_mem.recent_turns(orch.session_id)
        # 2 turns: user + assistant
        assert len(turns) == 2
        assert turns[0].role == "user"
        assert turns[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_recall_injects_into_prompt(self, tmp_mem):
        from modules.ai_router.router import AIRouter
        from modules.react_planner import ConversationOrchestrator
        from modules.react_planner.models import Action, PlannerDecision

        tmp_mem.add_memory("User is allergic to peanuts", kind=MemoryKind.FACT)

        router = AIRouter()
        orch = ConversationOrchestrator(router, memory=tmp_mem)

        captured_contexts: list[str] = []

        async def fake_decide(self, ctx):
            captured_contexts.append(ctx.screen_context_block)
            return PlannerDecision(action=Action.TEACH)

        async def fake_stream(self, msg, model_override=None, provider_override=None):
            yield "Ok"

        with patch("modules.react_planner.planner.ReActPlanner.decide", fake_decide):
            with patch("modules.ai_router.router.AIRouter.stream_response", fake_stream):
                async for _ in orch.handle_message("food recommendations"):
                    pass

        assert any("peanuts" in c for c in captured_contexts)
        assert any("RELEVANT MEMORY" in c for c in captured_contexts)
