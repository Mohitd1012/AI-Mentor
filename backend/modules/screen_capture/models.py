"""
Data models for the screen capture pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class ContentType(str, Enum):
    CODE       = "code"
    TERMINAL   = "terminal"
    BROWSER    = "browser"
    DOCUMENT   = "document"
    SPREADSHEET = "spreadsheet"
    CHAT       = "chat"
    EMAIL      = "email"
    UNKNOWN    = "unknown"


@dataclass
class BoundingBox:
    x: float      # normalized 0–1
    y: float
    width: float
    height: float


@dataclass
class TextObservation:
    text: str
    confidence: float
    bbox: BoundingBox


@dataclass
class ActiveApp:
    name: str
    bundle_id: str
    pid: int


@dataclass
class ScreenContext:
    """
    Fully structured representation of what is currently on screen.
    Passed to the AI router as system context on every turn.
    """
    timestamp: float = field(default_factory=time.time)

    # App info
    active_app: Optional[ActiveApp] = None

    # Raw OCR
    raw_text: str = ""
    observations: list[TextObservation] = field(default_factory=list)

    # Extracted entities
    content_type: ContentType = ContentType.UNKNOWN
    file_path: Optional[str] = None      # detected from title bar or content
    urls: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)

    # Masked version (safe to send to AI)
    masked_text: str = ""

    # Capture health
    is_blank: bool = False               # True = screen recording permission denied
    capture_width: int = 0
    capture_height: int = 0

    def to_prompt_block(self) -> str:
        """
        Renders a concise context block to inject into the AI system prompt.
        Returns empty string when there's nothing useful.
        """
        if self.is_blank or not self.masked_text.strip():
            return ""

        lines = ["[SCREEN CONTEXT]"]

        if self.active_app:
            lines.append(f"App: {self.active_app.name}")

        lines.append(f"Content type: {self.content_type.value}")

        if self.file_path:
            lines.append(f"File: {self.file_path}")

        if self.error_messages:
            lines.append("Errors detected:")
            for e in self.error_messages[:3]:
                lines.append(f"  • {e}")

        if self.urls:
            lines.append(f"URLs: {', '.join(self.urls[:3])}")

        # Truncate raw text to avoid blowing up context window
        text = self.masked_text.strip()
        if len(text) > 1500:
            text = text[:1500] + "\n... [truncated]"
        lines.append(f"Screen text:\n{text}")

        lines.append("[/SCREEN CONTEXT]")
        return "\n".join(lines)
