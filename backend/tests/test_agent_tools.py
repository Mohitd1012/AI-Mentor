"""
Tests for the Tier-1 agent tool kit.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.agent_tools import ToolCall, ToolDefinition, ToolRegistry
from modules.agent_tools.builtins import (
    SearchMemoryTool, SaveMemoryTool, RecallConversationTool, GetScreenContextTool,
)
from modules.memory_manager import MemoryManager, MemoryKind


@pytest.fixture
def tmp_mem(tmp_path: Path):
    return MemoryManager(
        sqlite_path=tmp_path / "test.db",
        chroma_dir=tmp_path / "chroma",
        extraction_enabled=False,
    )


# ── Registry ─────────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_register_and_get(self, tmp_mem):
        reg = ToolRegistry()
        tool = SearchMemoryTool(tmp_mem)
        reg.register(tool)
        assert reg.has("search_memory")
        assert reg.get("search_memory") is tool

    def test_register_twice_raises(self, tmp_mem):
        reg = ToolRegistry()
        reg.register(SearchMemoryTool(tmp_mem))
        with pytest.raises(ValueError):
            reg.register(SearchMemoryTool(tmp_mem))

    def test_definitions_list(self, tmp_mem):
        reg = ToolRegistry()
        reg.register(SearchMemoryTool(tmp_mem))
        reg.register(SaveMemoryTool(tmp_mem))
        defs = reg.definitions()
        names = {d.name for d in defs}
        assert names == {"search_memory", "save_memory"}

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, tmp_mem):
        reg = ToolRegistry()
        result = await reg.execute(ToolCall(id="x", name="nope", arguments={}))
        assert result.is_error is True
        assert "Unknown tool" in result.content

    @pytest.mark.asyncio
    async def test_execute_catches_exceptions(self, tmp_mem):
        reg = ToolRegistry()
        bad = MagicMock()
        bad.definition = ToolDefinition(name="bad", description="x",
                                         parameters_schema={"type": "object"})

        async def boom(args):
            raise RuntimeError("kaboom")
        bad.execute = boom

        reg.register(bad)
        result = await reg.execute(ToolCall(id="x", name="bad"))
        assert result.is_error is True
        assert "kaboom" in result.content


# ── search_memory ────────────────────────────────────────────────────────────

class TestSearchMemoryTool:
    @pytest.mark.asyncio
    async def test_returns_relevant(self, tmp_mem):
        tmp_mem.add_memory("User loves Python and async programming",
                           kind=MemoryKind.PREFERENCE)
        tool = SearchMemoryTool(tmp_mem)
        result = await tool.execute({"query": "snake language asyncio"})
        assert "Python" in result.content
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_empty_query_errors(self, tmp_mem):
        tool = SearchMemoryTool(tmp_mem)
        result = await tool.execute({"query": ""})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_mem):
        tool = SearchMemoryTool(tmp_mem)
        result = await tool.execute({"query": "completely unrelated alien dragon stuff"})
        assert "No relevant memories found" in result.content

    @pytest.mark.asyncio
    async def test_k_clamped(self, tmp_mem):
        tmp_mem.add_memory("a python fact one", kind=MemoryKind.FACT)
        tmp_mem.add_memory("a python fact two", kind=MemoryKind.FACT)
        tool = SearchMemoryTool(tmp_mem)
        result = await tool.execute({"query": "python", "k": 999})
        assert result.is_error is False


# ── save_memory ──────────────────────────────────────────────────────────────

class TestSaveMemoryTool:
    @pytest.mark.asyncio
    async def test_saves_with_default_kind(self, tmp_mem):
        tool = SaveMemoryTool(tmp_mem)
        result = await tool.execute({"content": "User uses VSCode as primary editor"})
        assert result.is_error is False
        assert "Saved memory" in result.content
        assert tmp_mem.list_memories()[0].content == "User uses VSCode as primary editor"

    @pytest.mark.asyncio
    async def test_saves_with_explicit_kind(self, tmp_mem):
        tool = SaveMemoryTool(tmp_mem)
        result = await tool.execute({
            "content": "User is preparing for system design interviews",
            "kind": "goal",
        })
        assert result.is_error is False
        mem = tmp_mem.list_memories()[0]
        assert mem.kind == MemoryKind.GOAL

    @pytest.mark.asyncio
    async def test_too_short_content_errors(self, tmp_mem):
        tool = SaveMemoryTool(tmp_mem)
        result = await tool.execute({"content": "hi"})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_too_long_content_errors(self, tmp_mem):
        tool = SaveMemoryTool(tmp_mem)
        result = await tool.execute({"content": "x" * 300})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_unknown_kind_falls_back_to_note(self, tmp_mem):
        tool = SaveMemoryTool(tmp_mem)
        result = await tool.execute({"content": "Some valid content here",
                                     "kind": "banana"})
        assert result.is_error is False
        assert tmp_mem.list_memories()[0].kind == MemoryKind.NOTE


# ── recall_conversation ──────────────────────────────────────────────────────

class TestRecallConversationTool:
    @pytest.mark.asyncio
    async def test_finds_matching_turn(self, tmp_mem):
        tmp_mem.save_user_turn("session-1",
                                "Let's talk about Kubernetes networking", "default")
        tmp_mem.save_assistant_turn("session-1",
                                     "Sure — what aspect interests you?", "default")
        tool = RecallConversationTool(tmp_mem, lambda: "session-1")
        result = await tool.execute({"query": "kubernetes"})
        assert result.is_error is False
        assert "Kubernetes" in result.content or "kubernetes" in result.content.lower()

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_mem):
        tmp_mem.save_user_turn("s", "hello", "default")
        tool = RecallConversationTool(tmp_mem, lambda: "s")
        result = await tool.execute({"query": "xyz123notthere"})
        assert "No past turns matched" in result.content

    @pytest.mark.asyncio
    async def test_empty_query_errors(self, tmp_mem):
        tool = RecallConversationTool(tmp_mem, lambda: "s")
        result = await tool.execute({"query": ""})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_limit_respected(self, tmp_mem):
        for i in range(10):
            tmp_mem.save_user_turn("s", f"talking about pytest item {i}", "default")
        tool = RecallConversationTool(tmp_mem, lambda: "s")
        result = await tool.execute({"query": "pytest", "limit": 3})
        # Should mention 3 (or fewer) matches in the rendered text
        assert "3" in result.content or len(result.details["matches"]) <= 3


# ── get_screen_context ───────────────────────────────────────────────────────

class TestGetScreenContextTool:
    @pytest.mark.asyncio
    async def test_warming_up(self):
        capture = MagicMock()
        capture.last_context = None
        tool = GetScreenContextTool(capture)
        result = await tool.execute({})
        assert "warming up" in result.content.lower()

    @pytest.mark.asyncio
    async def test_blank_screen(self):
        from modules.screen_capture.models import ScreenContext, ContentType
        capture = MagicMock()
        capture.last_context = ScreenContext(
            is_blank=True, masked_text="", content_type=ContentType.UNKNOWN,
            capture_width=0, capture_height=0,
        )
        tool = GetScreenContextTool(capture)
        result = await tool.execute({})
        assert "permission" in result.content.lower() or "blank" in result.content.lower()

    @pytest.mark.asyncio
    async def test_returns_context_block(self):
        from modules.screen_capture.models import (
            ScreenContext, ContentType, ActiveApp,
        )
        capture = MagicMock()
        capture.last_context = ScreenContext(
            active_app=ActiveApp(name="VSCode", bundle_id="x", pid=1),
            masked_text="def hello(): pass",
            raw_text="def hello(): pass",
            content_type=ContentType.CODE,
            file_path="/tmp/x.py",
            capture_width=1920, capture_height=1080,
        )
        tool = GetScreenContextTool(capture)
        result = await tool.execute({})
        assert "VSCode" in result.content
        assert result.details["content_type"] == "code"
