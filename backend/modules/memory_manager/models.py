"""
Memory data models.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class MemoryKind(str, Enum):
    PREFERENCE = "preference"   # "user prefers concise answers"
    FACT       = "fact"         # "user is a Python developer"
    GOAL       = "goal"         # "preparing for system design interview"
    PROJECT    = "project"      # "building an AI mentor app"
    NOTE       = "note"         # generic catch-all
    PINNED     = "pinned"       # user-pinned, never auto-decays


class Memory(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    kind: MemoryKind = MemoryKind.NOTE
    source: str = "auto"        # "auto" (extracted) | "user" (manually added)
    role_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    enabled: bool = True


class ConversationTurn(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    role: str                   # "user" | "assistant"
    content: str
    role_id: Optional[str] = None  # active mentor role at the time
    created_at: datetime = Field(default_factory=datetime.utcnow)
