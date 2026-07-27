"""
ReAct Planner — Observe → Understand → Decide.

The planner classifies the user's situation and returns a PlannerDecision.
The classifier call uses a small fast model (qwen2.5:3b by default).
"""

import json
import logging
import re
from typing import Optional

from config import get_settings
from modules.ai_router import ollama_client
from modules.react_planner.models import (
    Action, ConversationContext, ConversationMode, PlannerDecision,
)
from modules.react_planner.prompts import (
    CLASSIFIER_SYSTEM, build_classifier_user_prompt,
)
from modules.react_planner.policy import apply_policy

logger = logging.getLogger(__name__)


# Try to find {...} block even when wrapped in prose/markdown
_JSON_BLOCK_RE = re.compile(r'\{[^{}]*"action"[^{}]*\}', re.DOTALL)


class ReActPlanner:
    def __init__(self, classifier_model: Optional[str] = None) -> None:
        settings = get_settings()
        self._model = classifier_model or "qwen2.5:3b"
        self._base_url = settings.ollama_base_url

    async def decide(
        self,
        context: ConversationContext,
    ) -> PlannerDecision:
        """Run Observe → Understand → Decide and return the chosen action."""
        # ── Observe + Understand ────────────────────────────────────────────────
        raw = await self._classify(context)
        decision = self._parse_decision(raw)

        # ── Decide (policy layer) ──────────────────────────────────────────────
        final = apply_policy(
            decision,
            mode=context.mode,
            proactivity=context.proactivity,
            user_message=context.user_message,
        )

        logger.info(
            "[planner] action=%s mode=%s proactivity=%d  reason=%s",
            final.action.value, context.mode.value, context.proactivity,
            final.reasoning,
        )
        return final

    # ── Internal ────────────────────────────────────────────────────────────

    async def _classify(self, context: ConversationContext) -> str:
        user_prompt = build_classifier_user_prompt(
            user_message=context.user_message,
            screen_context_block=context.screen_context_block,
            recent_turns=context.recent_turns,
        )
        messages = [
            {"role": "system", "content": CLASSIFIER_SYSTEM},
            {"role": "user",   "content": user_prompt},
        ]
        chunks: list[str] = []
        try:
            async for chunk in ollama_client.stream_chat(
                self._base_url, self._model, messages
            ):
                chunks.append(chunk)
                # Stop early once we have a complete JSON object
                joined = "".join(chunks)
                if joined.count("{") > 0 and joined.count("{") == joined.count("}"):
                    break
        except Exception as exc:
            logger.warning("[planner] classifier failed: %s — defaulting to TEACH", exc)
            return ""

        return "".join(chunks)

    def _parse_decision(self, raw: str) -> PlannerDecision:
        """Robust JSON extraction with fallback to TEACH."""
        if not raw.strip():
            return PlannerDecision(action=Action.TEACH, reasoning="classifier empty → default")

        match = _JSON_BLOCK_RE.search(raw)
        candidate = match.group(0) if match else raw.strip()

        try:
            data = json.loads(candidate)
            action_str = str(data.get("action", "teach")).lower().strip()
            try:
                action = Action(action_str)
            except ValueError:
                logger.warning("[planner] unknown action '%s' → default", action_str)
                action = Action.TEACH
            return PlannerDecision(
                action=action,
                reasoning=str(data.get("reasoning", "")).strip()[:200],
            )
        except json.JSONDecodeError:
            logger.warning("[planner] JSON parse failed for: %.120s → default", raw)
            return PlannerDecision(action=Action.TEACH, reasoning="parse error → default")
