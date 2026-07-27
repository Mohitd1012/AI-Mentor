from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VoiceMode(str, Enum):
    OFF            = "off"
    PUSH_TO_TALK   = "push_to_talk"
    ALWAYS_LISTENING = "always_listening"


class VoiceState(str, Enum):
    IDLE        = "idle"
    LISTENING   = "listening"    # recording audio
    TRANSCRIBING = "transcribing"
    SPEAKING    = "speaking"     # TTS playing


@dataclass
class TranscriptResult:
    text: str
    is_final: bool
    language: str = "en"
    duration_s: float = 0.0


@dataclass
class TTSRequest:
    text: str
    voice: str = "Samantha"
    rate: int = 175              # words per minute (say -r flag)
    interrupt_current: bool = True
