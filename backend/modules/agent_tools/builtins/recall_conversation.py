"""
recall_conversation — search past conversation turns by text substring.

Useful when the user references "what we talked about earlier" but the
relevant turn is outside the orchestrator's rolling history window.
"""

from typing import Any

from modules.agent_tools.models import ToolDefinition, ToolResult
from modules.memory_manager import MemoryManager


class RecallConversationTool:
    definition = ToolDefinition(
        name="recall_conversation",
        description=(
            "Search past conversation turns from any earlier session for a "
            "substring match. Use when the user references something "
            "discussed before that isn't in the current visible history."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Word or phrase to search for in past turns.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max matches to return (default 5)",
                    "minimum": 1, "maximum": 20,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )

    def __init__(self, memory: MemoryManager, session_id_provider) -> None:
        """
        `session_id_provider` is a zero-arg callable returning the current
        session id — we depend on the orchestrator without importing it.
        """
        self._memory = memory
        self._session_id = session_id_provider

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip().lower()
        limit = int(args.get("limit", 5))
        limit = max(1, min(20, limit))

        if not query:
            return ToolResult(call_id="", is_error=True,
                              content="Error: 'query' is required")

        # Pull a generous window of recent turns from the current session
        # and filter by substring. Cheap & deterministic.
        try:
            session_id = self._session_id() or ""
            turns = self._memory.recent_turns(session_id, limit=200)
        except Exception as exc:
            return ToolResult(call_id="", is_error=True,
                              content=f"Could not access conversation history: {exc}")

        matches = []
        for t in turns:
            if query in t.content.lower():
                matches.append({
                    "role": t.role,
                    "content": t.content[:240],
                    "at": t.created_at.isoformat() if t.created_at else None,
                })
                if len(matches) >= limit:
                    break

        if not matches:
            return ToolResult(
                call_id="", content=f"No past turns matched '{query}'.",
                details={"query": query, "count": 0},
            )

        # Render as a compact text block for the model
        lines = [f"Found {len(matches)} matching turn(s) for '{query}':"]
        for m in matches:
            lines.append(f"  [{m['role']}] {m['content']}")
        return ToolResult(
            call_id="", content="\n".join(lines),
            details={"query": query, "matches": matches},
        )
