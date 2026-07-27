"""
save_memory — write a durable fact to long-term memory.
"""

from typing import Any

from modules.agent_tools.models import ToolDefinition, ToolResult
from modules.memory_manager import MemoryKind, MemoryManager


_VALID_KINDS = {k.value for k in MemoryKind}


class SaveMemoryTool:
    definition = ToolDefinition(
        name="save_memory",
        description=(
            "Permanently remember a fact about the user. Use when the user "
            "tells you something durable (preferences, goals, projects, "
            "important context). Don't save transient details or restated "
            "questions."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "One short, self-contained sentence stating the fact.",
                },
                "kind": {
                    "type": "string",
                    "description": "Category of memory",
                    "enum": ["preference", "fact", "goal", "project", "note", "pinned"],
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    )

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        content = str(args.get("content", "")).strip()
        kind_str = str(args.get("kind", "note")).lower().strip()

        if not content or len(content) < 5:
            return ToolResult(call_id="", is_error=True,
                              content="Error: 'content' too short or missing")
        if len(content) > 280:
            return ToolResult(call_id="", is_error=True,
                              content="Error: 'content' too long (max 280 chars)")
        if kind_str not in _VALID_KINDS:
            kind_str = "note"

        mem = self._memory.add_memory(content=content, kind=MemoryKind(kind_str))
        return ToolResult(
            call_id="",
            content=f"Saved memory ({mem.kind.value}): {mem.content}",
            details={"id": mem.id, "kind": mem.kind.value, "content": mem.content},
        )
