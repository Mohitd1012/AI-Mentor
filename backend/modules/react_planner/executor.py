"""
Action Executor — runs the chosen action against the executor LLM.

Wraps AIRouter so the action's system prompt overrides the default,
and supports cancellation via CancellationToken.
"""

import logging
from typing import AsyncIterator, Optional

from modules.ai_router.router import AIRouter
from modules.react_planner.cancellation import CancellationToken
from modules.react_planner.models import Action, ConversationContext
from modules.react_planner.prompts import build_executor_system_prompt

logger = logging.getLogger(__name__)


class ActionExecutor:
    def __init__(self, router: AIRouter) -> None:
        self._router = router

    async def execute(
        self,
        action: Action,
        context: ConversationContext,
        is_voice: bool = False,
        model_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        token: Optional[CancellationToken] = None,
    ) -> AsyncIterator[str]:
        """
        Yields response chunks. Stops immediately if `token` is cancelled.
        """
        # Build a system prompt tailored to the chosen action
        system_prompt = build_executor_system_prompt(
            action=action.value,
            base_prompt=self._router._base_prompt,
            screen_context_block=context.screen_context_block,
            is_voice=is_voice,
        )

        # Temporarily override the router's base prompt for this turn
        original_prompt = self._router._base_prompt
        original_screen = self._router._screen_context_block
        self._router._base_prompt = system_prompt
        # Screen context is already baked into system_prompt, so clear the auto-injection
        self._router._screen_context_block = ""

        try:
            async for chunk in self._router.stream_response(
                context.user_message,
                model_override=model_override,
                provider_override=provider_override,
            ):
                if token and token.cancelled:
                    logger.info("[executor] cancelled mid-stream")
                    return
                yield chunk
        finally:
            self._router._base_prompt = original_prompt
            self._router._screen_context_block = original_screen
