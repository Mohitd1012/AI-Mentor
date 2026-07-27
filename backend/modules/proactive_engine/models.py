"""
Data models + config for the proactive engine.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TriggerKind(str, Enum):
    STUCK         = "stuck"           # user lingering on same screen too long
    ERROR_LOOP    = "error_loop"      # repeated error messages
    CONTEXT_SHIFT = "context_shift"   # app or file changed
    IDLE          = "idle"            # long idle period
    SCREEN_CHANGE = "screen_change"   # Agent Mode: meaningful screen delta


@dataclass
class TriggerEvent:
    kind: TriggerKind
    summary: str                       # one-liner shown to AI as context
    details: dict = field(default_factory=dict)


@dataclass
class LevelConfig:
    """Behaviour profile for one proactivity level (0–4)."""
    stuck_seconds:        Optional[int]   # None = trigger disabled
    error_loop_min_count: Optional[int]
    context_shift:        bool
    idle_seconds:         Optional[int]
    cooldown_seconds:     int             # min seconds between any two fires
    # Agent-Mode-only fields. Default to "disabled" so non-agent levels are unaffected.
    screen_change:        bool = False
    screen_change_min_diff: float = 0.4   # fraction of new tokens to count as "meaningful"


# Maps proactivity level → behaviour
LEVELS: dict[int, LevelConfig] = {
    0: LevelConfig(None, None, False, None,  cooldown_seconds=10**9),
    1: LevelConfig(None, None, False, None,  cooldown_seconds=10**9),
    2: LevelConfig(stuck_seconds=600, error_loop_min_count=3,
                   context_shift=False, idle_seconds=None, cooldown_seconds=300),
    3: LevelConfig(stuck_seconds=300, error_loop_min_count=3,
                   context_shift=True,  idle_seconds=1800, cooldown_seconds=180),
    4: LevelConfig(stuck_seconds=180, error_loop_min_count=2,
                   context_shift=True,  idle_seconds=900,  cooldown_seconds=90),
}

# Agent Mode = continuous narration. Aggressive cooldown + screen-change trigger.
AGENT_MODE_CONFIG = LevelConfig(
    stuck_seconds=120,
    error_loop_min_count=2,
    context_shift=True,
    idle_seconds=600,
    cooldown_seconds=25,             # ~25s between proactive turns
    screen_change=True,
    screen_change_min_diff=0.35,     # 35% new tokens → comment-worthy change
)
