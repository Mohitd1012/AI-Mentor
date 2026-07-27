"""
get_screen_context — fetch a fresh snapshot of what's currently on screen.
"""

from typing import Any

from modules.agent_tools.models import ToolDefinition, ToolResult
from modules.screen_capture import ScreenCaptureEngine


class GetScreenContextTool:
    definition = ToolDefinition(
        name="get_screen_context",
        description=(
            "Get the latest snapshot of what's on the user's screen — active "
            "app, file path, errors, URLs, and OCR text. Use this when you "
            "need to verify the current state of the screen, not what it "
            "looked like at the start of this turn."
        ),
        parameters_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )

    def __init__(self, capture: ScreenCaptureEngine) -> None:
        self._capture = capture

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        ctx = self._capture.last_context
        if ctx is None:
            return ToolResult(call_id="",
                              content="No screen capture yet (engine still warming up).",
                              details={})

        if ctx.is_blank:
            return ToolResult(
                call_id="",
                content=(
                    "Screen appears blank — Screen Recording permission "
                    "is probably missing. Tell the user to grant it under "
                    "System Settings → Privacy & Security → Screen Recording."
                ),
                details={"is_blank": True},
            )

        block = ctx.to_prompt_block() or "No useful content on screen right now."
        return ToolResult(
            call_id="",
            content=block,
            details={
                "app": ctx.active_app.name if ctx.active_app else None,
                "content_type": ctx.content_type.value,
                "file": ctx.file_path,
                "errors": ctx.error_messages[:3],
                "urls": ctx.urls[:3],
            },
        )
