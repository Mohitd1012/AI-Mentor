"""
SQLite store for conversations + structured memories.

Two tables:
  conversations — raw user/assistant turns (audit trail)
  memories       — distilled long-term facts (also indexed in vector store)

Both shapes mirror the Pydantic models in `models.py`.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from modules.memory_manager.models import (
    ConversationTurn, Memory, MemoryKind,
)

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "memory.db"


class SQLiteStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or _DEFAULT_DB
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    role_id     TEXT,
                    created_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
                CREATE INDEX IF NOT EXISTS idx_conv_created ON conversations(created_at);

                CREATE TABLE IF NOT EXISTS memories (
                    id          TEXT PRIMARY KEY,
                    content     TEXT NOT NULL,
                    kind        TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    role_id     TEXT,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    enabled     INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind);
                CREATE INDEX IF NOT EXISTS idx_mem_enabled ON memories(enabled);
            """)
            self._conn.commit()

    # ── Conversations ────────────────────────────────────────────────────────

    def add_turn(self, turn: ConversationTurn) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO conversations
                   (id, session_id, role, content, role_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (turn.id, turn.session_id, turn.role, turn.content,
                 turn.role_id, turn.created_at.isoformat()),
            )
            self._conn.commit()

    def recent_turns(self, session_id: str, limit: int = 20) -> list[ConversationTurn]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM conversations
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        # Return chronological order
        return [self._row_to_turn(r) for r in reversed(rows)]

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> ConversationTurn:
        return ConversationTurn(
            id=row["id"], session_id=row["session_id"],
            role=row["role"], content=row["content"],
            role_id=row["role_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ── Memories ─────────────────────────────────────────────────────────────

    def upsert_memory(self, mem: Memory) -> Memory:
        mem.updated_at = datetime.utcnow()
        with self._lock:
            self._conn.execute(
                """INSERT INTO memories
                   (id, content, kind, source, role_id, created_at, updated_at, enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     content   = excluded.content,
                     kind      = excluded.kind,
                     source    = excluded.source,
                     role_id   = excluded.role_id,
                     updated_at = excluded.updated_at,
                     enabled   = excluded.enabled""",
                (mem.id, mem.content, mem.kind.value, mem.source, mem.role_id,
                 mem.created_at.isoformat(), mem.updated_at.isoformat(),
                 1 if mem.enabled else 0),
            )
            self._conn.commit()
        return mem

    def get_memory(self, memory_id: str) -> Optional[Memory]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return self._row_to_memory(row) if row else None

    def list_memories(
        self,
        enabled_only: bool = False,
        kind: Optional[MemoryKind] = None,
    ) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list = []
        if enabled_only:
            sql += " AND enabled = 1"
        if kind:
            sql += " AND kind = ?"
            params.append(kind.value)
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def set_enabled(self, memory_id: str, enabled: bool) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, datetime.utcnow().isoformat(), memory_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def clear_all_memories(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories")
            self._conn.commit()
            return cur.rowcount

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"], content=row["content"],
            kind=MemoryKind(row["kind"]),
            source=row["source"], role_id=row["role_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            enabled=bool(row["enabled"]),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
