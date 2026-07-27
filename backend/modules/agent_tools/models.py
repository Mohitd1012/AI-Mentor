"""
Internal tool-calling data model.

Provider clients translate to/from these. The orchestrator + UI only
ever see these neutral shapes.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolDefinition:
    """How a tool is advertised to the model."""
    name: str
    description: str
    parameters_schema: dict   # JSON Schema for the `arguments` object


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""
    id: str                   # provider-issued (or our fallback) — used to pair with result
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result fed back to the model after executing a ToolCall."""
    call_id: str
    content: str              # always serialised to string for the model
    is_error: bool = False
    # Structured details kept for the UI but not always shown to the model
    details: Optional[dict] = None
