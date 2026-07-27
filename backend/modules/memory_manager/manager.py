"""
MemoryManager — the unified high-level API.

  • recall(query, k)  → returns formatted [RELEVANT MEMORY] block for prompts
  • save_turn(...)     → persists conversation + extracts memories async
  • add_memory(...)    → user-added memory
  • list / update / delete / disable
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from modules.memory_manager.models import (
    ConversationTurn, Memory, MemoryKind,
)
from modules.memory_manager.sqlite_store import SQLiteStore
from modules.memory_manager.vector_store import VectorStore
from modules.memory_manager import extractor

logger = logging.getLogger(__name__)

DEFAULT_RECALL_K  = 3
MAX_BLOCK_CHARS   = 600   # cap injected context


class MemoryManager:
    def __init__(
        self,
        sqlite_path: Optional[Path] = None,
        chroma_dir:  Optional[Path] = None,
        extraction_enabled: bool = True,
    ) -> None:
        self._sql    = SQLiteStore(sqlite_path)
        self._vec    = VectorStore(chroma_dir)
        self._extract = extraction_enabled
        # Rebuild the vector index from SQLite if it's empty but SQLite isn't
        self._reconcile()

    def _reconcile(self) -> None:
        if self._vec.count() == 0:
            mems = self._sql.list_memories(enabled_only=False)
            if mems:
                logger.info("[memory] reseeding vector store with %d memories", len(mems))
                for m in mems:
                    self._vec.upsert(m.id, m.content, self._meta(m))

    @staticmethod
    def _meta(m: Memory) -> dict:
        return {
            "kind": m.kind.value,
            "source": m.source,
            "enabled": m.enabled,
            "role_id": m.role_id or "",
        }

    # ── Recall ───────────────────────────────────────────────────────────────

    def recall(self, query: str, k: int = DEFAULT_RECALL_K) -> str:
        """Return a formatted [RELEVANT MEMORY] block. Empty if nothing relevant."""
        hits = self._vec.search(query, n_results=k, where={"enabled": True})
        if not hits:
            return ""

        lines: list[str] = ["[RELEVANT MEMORY]"]
        budget = MAX_BLOCK_CHARS
        for h in hits:
            kind = (h.get("metadata") or {}).get("kind", "note")
            line = f"• ({kind}) {h['content']}"
            if budget - len(line) < 0:
                break
            lines.append(line)
            budget -= len(line)
        lines.append("[/RELEVANT MEMORY]")
        return "\n".join(lines)

    # ── Persistence ──────────────────────────────────────────────────────────

    def save_user_turn(self, session_id: str, content: str, role_id: Optional[str]) -> None:
        self._sql.add_turn(ConversationTurn(
            session_id=session_id, role="user", content=content, role_id=role_id,
        ))

    def save_assistant_turn(self, session_id: str, content: str, role_id: Optional[str]) -> None:
        self._sql.add_turn(ConversationTurn(
            session_id=session_id, role="assistant", content=content, role_id=role_id,
        ))

    async def extract_async(
        self,
        user_msg: str,
        assistant_msg: str,
        role_id: Optional[str] = None,
    ) -> list[Memory]:
        """
        Fire-and-forget fact extraction. Returns the list of saved memories.
        Safe to call from a background task; never raises.
        """
        if not self._extract:
            return []
        try:
            mems = await extractor.extract_memories(user_msg, assistant_msg, role_id)
        except Exception:
            logger.exception("[memory] extraction error")
            return []

        saved: list[Memory] = []
        for m in mems:
            try:
                self._sql.upsert_memory(m)
                self._vec.upsert(m.id, m.content, self._meta(m))
                saved.append(m)
            except Exception:
                logger.exception("[memory] failed to save %s", m.id)
        if saved:
            logger.info("[memory] extracted %d new memor(y/ies): %s",
                        len(saved), [m.content[:60] for m in saved])
        return saved

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_memory(self, content: str, kind: MemoryKind = MemoryKind.NOTE,
                   role_id: Optional[str] = None) -> Memory:
        m = Memory(content=content, kind=kind, source="user", role_id=role_id)
        self._sql.upsert_memory(m)
        self._vec.upsert(m.id, m.content, self._meta(m))
        return m

    def update_memory(self, memory_id: str, content: Optional[str] = None,
                      kind: Optional[MemoryKind] = None,
                      enabled: Optional[bool] = None) -> Optional[Memory]:
        m = self._sql.get_memory(memory_id)
        if not m:
            return None
        if content is not None:
            m.content = content
        if kind is not None:
            m.kind = kind
        if enabled is not None:
            m.enabled = enabled
        self._sql.upsert_memory(m)
        self._vec.upsert(m.id, m.content, self._meta(m))
        return m

    def delete_memory(self, memory_id: str) -> bool:
        ok = self._sql.delete_memory(memory_id)
        if ok:
            self._vec.delete(memory_id)
        return ok

    def list_memories(self, enabled_only: bool = False,
                      kind: Optional[MemoryKind] = None) -> list[Memory]:
        return self._sql.list_memories(enabled_only=enabled_only, kind=kind)

    def clear_all(self) -> int:
        n = self._sql.clear_all_memories()
        self._vec.clear()
        return n

    def set_extraction_enabled(self, enabled: bool) -> None:
        self._extract = enabled
        logger.info("[memory] auto-extraction %s", "enabled" if enabled else "disabled")

    @property
    def extraction_enabled(self) -> bool:
        return self._extract

    def recent_turns(self, session_id: str, limit: int = 20) -> list[ConversationTurn]:
        return self._sql.recent_turns(session_id, limit=limit)
