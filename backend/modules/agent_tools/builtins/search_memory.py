"""
search_memory — semantic search over the user's long-term memory.
"""

import json
from typing import Any

from modules.agent_tools.models import ToolDefinition, ToolResult
from modules.memory_manager import MemoryManager


class SearchMemoryTool:
    definition = ToolDefinition(
        name="search_memory",
        description=(
            "Search the user's long-term memory for relevant past facts, "
            "preferences, projects, or goals. Use this when you need context "
            "about the user that wasn't established in this conversation."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query",
                },
                "k": {
                    "type": "integer",
                    "description": "Maximum number of memories to return (default 3)",
                    "minimum": 1, "maximum": 10,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        k     = int(args.get("k", 3))
        k     = max(1, min(10, k))

        if not query:
            return ToolResult(call_id="", content="Error: 'query' is required",
                              is_error=True)

        block = self._memory.recall(query, k=k)
        if not block.strip():
            return ToolResult(call_id="", content="No relevant memories found.",
                              details={"query": query, "count": 0})

        return ToolResult(
            call_id="",
            content=block,
            details={"query": query, "k": k},
        )
