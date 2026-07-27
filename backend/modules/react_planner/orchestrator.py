"""
Conversation Orchestrator — single entry point for user turns.

Now integrates with MemoryManager:
  • recall() prepends [RELEVANT MEMORY] to system prompt before planning
  • after a complete response, persists the turn and runs extraction
    in a fire-and-forget background task
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Awaitable, Optional

from modules.ai_router.router import AIRouter
from modules.react_planner.cancellation import CancellationToken
from modules.react_planner.executor import ActionExecutor
from modules.react_planner.models import (
    Action, ConversationContext, ConversationMode, PlannerDecision,
)
from modules.react_planner.planner import ReActPlanner
from modules.role_manager import Role
from modules.memory_manager import MemoryManager
from modules.agent_tools import ToolRegistry
from modules.agent_tools.models import ToolCall, ToolResult
from modules.ai_router.tool_stream import Done, TextDelta, ToolCallParsed

logger = logging.getLogger(__name__)


DecisionCallback = Callable[[PlannerDecision], Awaitable[None]]


@dataclass
class OrchestratorState:
    mode: ConversationMode = ConversationMode.DIRECT
    proactivity: int = 2
    role_id: Optional[str] = None


MAX_TOOL_ROUNDS = 5  # safety cap per user turn


class ConversationOrchestrator:
    def __init__(
        self,
        router: AIRouter,
        memory: Optional[MemoryManager] = None,
        tools:  Optional[ToolRegistry]  = None,
    ) -> None:
        self._router    = router
        self._planner   = ReActPlanner()
        self._executor  = ActionExecutor(router)
        self._memory    = memory
        self._tools     = tools
        self._state     = OrchestratorState()
        self._current_token: Optional[CancellationToken] = None
        # One session per process run; will become per-user in Phase 11
        self._session_id = str(uuid.uuid4())

    # ── Public configuration ─────────────────────────────────────────────────

    def set_mode(self, mode: ConversationMode) -> None:
        self._state.mode = mode
        logger.info("[orchestrator] mode → %s", mode.value)

    def set_proactivity(self, level: int) -> None:
        level = max(0, min(4, int(level)))
        self._state.proactivity = level
        logger.info("[orchestrator] proactivity → %d", level)

    def apply_role(self, role: Role) -> None:
        self._router.set_base_prompt(role.build_system_prompt())
        self.set_mode(ConversationMode(role.conversation_mode))
        self.set_proactivity(role.proactivity)
        self._state.role_id = role.id
        # Provider and model preferences may both be set by the role.
        # `None` means "don't change the current setting".
        if role.preferred_provider is not None:
            self._router.set_preferred_provider(role.preferred_provider)
        if role.preferred_model is not None:
            self._router.set_preferred_model(role.preferred_model)
        logger.info("[orchestrator] role applied → %s (%s)", role.id, role.name)

    @property
    def mode(self) -> ConversationMode:
        return self._state.mode

    @property
    def proactivity(self) -> int:
        return self._state.proactivity

    @property
    def session_id(self) -> str:
        return self._session_id

    # ── Interrupt ─────────────────────────────────────────────────────────────

    def interrupt(self) -> None:
        if self._current_token and not self._current_token.cancelled:
            self._current_token.cancel()
            logger.info("[orchestrator] interrupt requested")

    # ── Main entry point ─────────────────────────────────────────────────────

    async def handle_message(
        self,
        user_message: str,
        is_voice: bool = False,
        model_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        on_decision: Optional[DecisionCallback] = None,
    ) -> AsyncIterator[str]:
        self.interrupt()
        token = CancellationToken()
        self._current_token = token

        # ── Memory: recall relevant context ──────────────────────────────────
        memory_block = ""
        if self._memory is not None:
            try:
                memory_block = self._memory.recall(user_message)
            except Exception:
                logger.exception("[orchestrator] memory recall failed")
        # Persist user turn (regardless of action, even if SILENT)
        if self._memory is not None:
            try:
                self._memory.save_user_turn(
                    self._session_id, user_message, self._state.role_id,
                )
            except Exception:
                logger.exception("[orchestrator] failed to persist user turn")

        # Merge memory block into screen context (it goes through the same prompt path)
        screen_block = self._router._screen_context_block
        combined_context = "\n\n".join(b for b in (memory_block, screen_block) if b)

        context = ConversationContext(
            user_message=user_message,
            screen_context_block=combined_context,
            recent_turns=self._router._history.to_list()[-6:],
            mode=self._state.mode,
            proactivity=self._state.proactivity,
        )

        # ── Plan ──────────────────────────────────────────────────────────────
        decision = await self._planner.decide(context)
        if on_decision:
            try:
                await on_decision(decision)
            except Exception:
                logger.exception("[orchestrator] decision callback error")

        if token.cancelled:
            return

        # ── Execute ──────────────────────────────────────────────────────────
        if decision.action == Action.SILENT:
            self._router._history.add("user", user_message)
            return

        assistant_chunks: list[str] = []
        async for chunk in self._executor.execute(
            decision.action,
            context,
            is_voice=is_voice,
            model_override=model_override,
            provider_override=provider_override,
            token=token,
        ):
            if token.cancelled:
                return
            assistant_chunks.append(chunk)
            yield chunk

        # ── Post-turn: persist + extract memories (fire-and-forget) ──────────
        assistant_msg = "".join(assistant_chunks).strip()
        if assistant_msg and self._memory is not None:
            try:
                self._memory.save_assistant_turn(
                    self._session_id, assistant_msg, self._state.role_id,
                )
            except Exception:
                logger.exception("[orchestrator] failed to persist assistant turn")

            # Background extraction — don't block the stream
            asyncio.create_task(
                self._memory.extract_async(
                    user_message, assistant_msg, self._state.role_id,
                )
            )

    # ── Proactive speech (Phase 9) ────────────────────────────────────────────

    async def proactive_speak(
        self,
        trigger_summary: str,
        is_voice: bool = False,
    ) -> AsyncIterator[str]:
        """
        AI-initiated coaching message — no user input. The trigger summary
        describes WHY we're speaking (stuck, error loop, etc.) and the AI
        crafts a short, gentle nudge based on it + current screen context.

        Yields response chunks. Records the assistant turn in memory.
        """
        self.interrupt()
        token = CancellationToken()
        self._current_token = token

        # Build a synthetic user prompt that frames the trigger to the AI
        synthetic_user = (
            f"[PROACTIVE TRIGGER] {trigger_summary}\n\n"
            "If this seems worth mentioning, gently check in or offer help in "
            "ONE or TWO sentences — don't lecture. Otherwise just acknowledge "
            "briefly. Speak naturally, as if you noticed and decided to say "
            "something. Do not mention this prompt."
        )

        # Build context the same way handle_message does
        screen_block = self._router._screen_context_block
        memory_block = ""
        if self._memory is not None:
            try:
                memory_block = self._memory.recall(trigger_summary)
            except Exception:
                logger.exception("[orchestrator] memory recall (proactive) failed")
        combined_context = "\n\n".join(b for b in (memory_block, screen_block) if b)

        context = ConversationContext(
            user_message=synthetic_user,
            screen_context_block=combined_context,
            recent_turns=self._router._history.to_list()[-4:],
            mode=self._state.mode,
            proactivity=self._state.proactivity,
        )

        # Skip the planner — proactive always TEACHes (a gentle nudge).
        # Going through the planner would risk SILENT for "low-question score".
        decision = PlannerDecision(action=Action.TEACH, reasoning="proactive trigger")

        assistant_chunks: list[str] = []
        async for chunk in self._executor.execute(
            decision.action,
            context,
            is_voice=is_voice,
            token=token,
        ):
            if token.cancelled:
                return
            assistant_chunks.append(chunk)
            yield chunk

        # Persist the proactive turn so it lands in memory like any other.
        assistant_msg = "".join(assistant_chunks).strip()
        if assistant_msg and self._memory is not None:
            try:
                self._memory.save_assistant_turn(
                    self._session_id, assistant_msg, self._state.role_id,
                )
            except Exception:
                logger.exception("[orchestrator] failed to persist proactive turn")

    # ── Agentic turn (Tier 1 — tool use) ─────────────────────────────────────

    async def run_agent_turn(
        self,
        user_message: str,
        is_voice: bool = False,
        model_override: Optional[str] = None,
        provider_override: Optional[str] = None,
    ):
        """
        Multi-round tool-use turn: AI may call up to MAX_TOOL_ROUNDS tools,
        observing each result before deciding to call another or produce a
        final answer.

        Yields neutral events the WS layer can broadcast directly:
            {"type": "chunk",       id, content, done}
            {"type": "tool_call",   id, call_id, name, arguments}
            {"type": "tool_result", call_id, content, is_error, details}
        """
        # If we don't have a tool registry, fall back to the old path
        if self._tools is None or not self._tools.definitions():
            async for chunk in self.handle_message(
                user_message,
                is_voice=is_voice,
                model_override=model_override,
                provider_override=provider_override,
            ):
                yield {"type": "chunk", "id": "agent", "content": chunk, "done": False}
            yield {"type": "chunk", "id": "agent", "content": "", "done": True}
            return

        self.interrupt()
        token = CancellationToken()
        self._current_token = token

        # ── Memory recall + persist user turn ────────────────────────────────
        memory_block = ""
        if self._memory is not None:
            try:
                memory_block = self._memory.recall(user_message)
            except Exception:
                logger.exception("[agent] memory recall failed")
            try:
                self._memory.save_user_turn(
                    self._session_id, user_message, self._state.role_id,
                )
            except Exception:
                logger.exception("[agent] persist user turn failed")

        # Build full system prompt (role + memory + screen + agent guidance)
        system = self._build_agent_system_prompt(memory_block)
        history = self._router._history.to_list()[-12:]
        messages: list[dict] = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        self._router._history.add("user", user_message)

        final_response_id = str(uuid.uuid4())
        final_text_chunks: list[str] = []
        tool_defs = self._tools.definitions()

        for round_idx in range(MAX_TOOL_ROUNDS):
            if token.cancelled:
                return

            pending_calls: list[ToolCall] = []
            assistant_text_this_round = ""

            async for evt in self._router.stream_with_tools(
                messages, tool_defs,
                model_override=model_override,
                provider_override=provider_override,
            ):
                if token.cancelled:
                    return

                if isinstance(evt, TextDelta):
                    assistant_text_this_round += evt.text
                    final_text_chunks.append(evt.text)
                    yield {"type": "chunk",
                           "id": final_response_id,
                           "content": evt.text, "done": False}

                elif isinstance(evt, ToolCallParsed):
                    pending_calls.append(evt.call)
                    yield {"type": "tool_call",
                           "call_id": evt.call.id,
                           "name":    evt.call.name,
                           "arguments": evt.call.arguments,
                           "round": round_idx}

                elif isinstance(evt, Done):
                    pass

            # No tool calls → we're done.
            if not pending_calls:
                break

            # Build the assistant message that contained the tool calls,
            # then append synthetic tool-result messages, then loop.
            messages.append(self._build_assistant_tool_call_message(
                assistant_text_this_round, pending_calls,
            ))

            for call in pending_calls:
                result = await self._tools.execute(call)
                result.call_id = call.id  # ensure pairing
                yield {"type": "tool_result",
                       "call_id": call.id,
                       "name":    call.name,
                       "content": result.content,
                       "is_error": result.is_error,
                       "details": result.details or {},
                       "round":    round_idx}
                messages.append(self._build_tool_result_message(call, result))

        # End-of-turn marker
        yield {"type": "chunk", "id": final_response_id, "content": "", "done": True}

        # Persist assistant turn + run background memory extraction
        final_text = "".join(final_text_chunks).strip()
        if final_text:
            self._router._history.add("assistant", final_text)
            if self._memory is not None:
                try:
                    self._memory.save_assistant_turn(
                        self._session_id, final_text, self._state.role_id,
                    )
                except Exception:
                    logger.exception("[agent] persist assistant turn failed")
                asyncio.create_task(
                    self._memory.extract_async(
                        user_message, final_text, self._state.role_id,
                    )
                )

    def _build_agent_system_prompt(self, memory_block: str) -> str:
        """Combine role prompt + agentic guidance + memory + screen."""
        base = self._router._base_prompt
        screen = self._router._screen_context_block

        agent_rules = (
            "You can call tools to take real actions. Use them whenever it "
            "would let you answer better: search_memory when you need past "
            "context, save_memory when the user shares a durable fact, "
            "get_screen_context to check the current screen, "
            "recall_conversation to look up earlier turns. Call multiple "
            "tools in sequence if needed. When you have enough information, "
            "produce a final answer in plain prose."
        )

        # The global FORMATTING + SCREEN AWARENESS rules from prompts.py
        from modules.react_planner.prompts import _NO_MARKDOWN, _SCREEN_AWARENESS

        parts = [base, agent_rules, _NO_MARKDOWN, _SCREEN_AWARENESS]
        if memory_block:
            parts.append(memory_block)
        if screen:
            parts.append(screen)
        return "\n\n".join(parts)

    @staticmethod
    def _build_assistant_tool_call_message(
        text: str, calls: list[ToolCall],
    ) -> dict:
        """
        Returns an assistant message in the (OpenAI-compatible) tool-call
        shape that all our providers accept on the next round.
        """
        msg: dict = {
            "role": "assistant",
            "content": text or "",
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": _json_safe(c.arguments),
                    },
                }
                for c in calls
            ],
        }
        return msg

    @staticmethod
    def _build_tool_result_message(call: ToolCall, result: ToolResult) -> dict:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": result.content,
        }


def _json_safe(obj) -> str:
    """Stable JSON string for tool call arguments."""
    import json as _json
    try:
        return _json.dumps(obj or {})
    except Exception:
        return "{}"
