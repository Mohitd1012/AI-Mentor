"""
Provider-neutral streaming events for tool-aware chat completions.

Each client's stream_with_tools() yields a sequence of these events:
  • TextDelta(text)           — a chunk of natural-language output
  • ToolCallParsed(call)      — a fully-assembled tool call ready to execute
  • Done()                    — end of this assistant turn

The orchestrator consumes the events, dispatches tool calls, appends results
to the message history, and re-invokes stream_with_tools until either:
  • The assistant emits Done() with no pending tool calls, or
  • The max-rounds cap is reached.
"""

from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Union

from modules.agent_tools.models import ToolCall


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallParsed:
    call: ToolCall


@dataclass
class Done:
    """Marks end of the current assistant message."""
    finish_reason: Optional[str] = None


StreamEvent = Union[TextDelta, ToolCallParsed, Done]
ToolStream  = AsyncIterator[StreamEvent]
