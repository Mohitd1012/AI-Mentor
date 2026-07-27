"""
Data models for the ReAct planner.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Action(str, Enum):
    TEACH     = "teach"      # direct answer + explanation
    ASK       = "ask"        # clarifying question first
    CHALLENGE = "challenge"  # Socratic: question the assumption
    SUMMARIZE = "summarize"  # recap progress / repeat back
    SILENT    = "silent"     # stay quiet


class ConversationMode(str, Enum):
    DIRECT      = "direct"       # default — answer well
    SOCRATIC    = "socratic"     # bias toward ASK/CHALLENGE
    THINK_ALOUD = "think_aloud"  # play back understanding, keep user talking


@dataclass
class PlannerDecision:
    action: Action
    reasoning: str = ""           # short rationale (shown in dev mode)
    mode_hint: Optional[str] = None  # planner-suggested mode shift


@dataclass
class ConversationContext:
    user_message: str
    screen_context_block: str = ""       # from ScreenCaptureEngine
    recent_turns: list[dict] = field(default_factory=list)
    mode: ConversationMode = ConversationMode.DIRECT
    proactivity: int = 2                  # 0–4
