from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


# ── Inbound (client → server) ──────────────────────────────────────────────

class ChatMessage(BaseModel):
    type: Literal["chat"]
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    model: Optional[str] = None
    role_id: Optional[str] = "default"


class PingMessage(BaseModel):
    type: Literal["ping"]


class PTTStartMessage(BaseModel):
    type: Literal["ptt_start"]


class PTTStopMessage(BaseModel):
    type: Literal["ptt_stop"]


class SetVoiceModeMessage(BaseModel):
    type: Literal["set_voice_mode"]
    mode: str   # "off" | "push_to_talk" | "always_listening"


# ── Outbound (server → client) ─────────────────────────────────────────────

class ChunkMessage(BaseModel):
    type: Literal["chunk"] = "chunk"
    id: str
    content: str
    done: bool = False


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    state: Literal["idle", "thinking", "speaking"]


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    message: str


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"


class VoiceStateMessage(BaseModel):
    type: Literal["voice_state"] = "voice_state"
    state: str   # VoiceState value
    mode: str    # VoiceMode value


class TranscriptMessage(BaseModel):
    type: Literal["transcript"] = "transcript"
    text: str
    is_final: bool = True
