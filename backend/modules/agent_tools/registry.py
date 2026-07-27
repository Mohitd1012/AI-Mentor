"""
Tool registry — the one place that knows which tools exist and how to run them.
"""

import json
import logging
from typing import Any, Awaitable, Callable, Protocol

from modules.agent_tools.models import ToolCall, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class Tool(Protocol):
    """A callable agent tool."""
    definition: ToolDefinition
    async def execute(self, args: dict[str, Any]) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool
        logger.info("[tools] registered %s", name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def definitions(self) -> list[ToolDefinition]:
        return [t.definition for t in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name not in self._tools:
            return ToolResult(
                call_id=call.id,
                content=f"Unknown tool: {call.name}",
                is_error=True,
            )
        try:
            return await self._tools[call.name].execute(call.arguments or {})
        except Exception as exc:
            logger.exception("[tools] execution failed: %s", call.name)
            return ToolResult(
                call_id=call.id,
                content=f"Error executing {call.name}: {exc}",
                is_error=True,
            )
