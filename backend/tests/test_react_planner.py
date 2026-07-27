"""
Tests for Phase 4 — ReAct Planner.
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from modules.react_planner.models import (
    Action, ConversationMode, ConversationContext, PlannerDecision,
)
from modules.react_planner.cancellation import CancellationToken
from modules.react_planner.policy import apply_policy
from modules.react_planner.planner import ReActPlanner
from modules.react_planner.orchestrator import ConversationOrchestrator
from modules.ai_router.router import AIRouter


# ── Cancellation ──────────────────────────────────────────────────────────────

class TestCancellation:
    def test_default_not_cancelled(self):
        t = CancellationToken()
        assert t.cancelled is False

    def test_cancel_sets_flag(self):
        t = CancellationToken()
        t.cancel()
        assert t.cancelled is True

    @pytest.mark.asyncio
    async def test_wait_resolves_on_cancel(self):
        t = CancellationToken()
        async def cancel_soon():
            await asyncio.sleep(0.01)
            t.cancel()
        asyncio.create_task(cancel_soon())
        await asyncio.wait_for(t.wait(), timeout=1.0)
        assert t.cancelled is True


# ── Policy ────────────────────────────────────────────────────────────────────

class TestPolicy:
    def _decision(self, action: Action, reasoning: str = "") -> PlannerDecision:
        return PlannerDecision(action=action, reasoning=reasoning)

    def test_direct_mode_passes_through(self):
        d = apply_policy(self._decision(Action.TEACH), ConversationMode.DIRECT, 2, "what is a closure?")
        assert d.action == Action.TEACH

    def test_socratic_teach_becomes_challenge(self):
        d = apply_policy(self._decision(Action.TEACH), ConversationMode.SOCRATIC, 2, "what is X?")
        assert d.action == Action.CHALLENGE

    def test_socratic_ask_unchanged(self):
        d = apply_policy(self._decision(Action.ASK), ConversationMode.SOCRATIC, 2, "what")
        assert d.action == Action.ASK

    def test_think_aloud_long_input_summarizes(self):
        long = "I have been working on this Kubernetes deployment all morning " \
               "and the pods keep crashing with OOMKilled and I tried bumping the memory limit but"
        d = apply_policy(self._decision(Action.TEACH), ConversationMode.THINK_ALOUD, 2, long)
        assert d.action == Action.SUMMARIZE

    def test_think_aloud_short_input_unchanged(self):
        d = apply_policy(self._decision(Action.TEACH), ConversationMode.THINK_ALOUD, 2, "what is k8s")
        assert d.action == Action.TEACH

    def test_proactivity_zero_silences_non_questions(self):
        d = apply_policy(self._decision(Action.TEACH), ConversationMode.DIRECT, 0, "I'm working on this")
        assert d.action == Action.SILENT

    def test_proactivity_zero_allows_questions(self):
        d = apply_policy(self._decision(Action.TEACH), ConversationMode.DIRECT, 0, "what is this?")
        assert d.action == Action.TEACH

    def test_proactivity_zero_allows_how_questions(self):
        d = apply_policy(self._decision(Action.TEACH), ConversationMode.DIRECT, 0, "how do I configure this")
        assert d.action == Action.TEACH


# ── Planner JSON parsing ──────────────────────────────────────────────────────

class TestPlannerParsing:
    def test_clean_json(self):
        planner = ReActPlanner()
        d = planner._parse_decision('{"action": "ask", "reasoning": "ambiguous"}')
        assert d.action == Action.ASK
        assert d.reasoning == "ambiguous"

    def test_json_with_markdown_wrapper(self):
        planner = ReActPlanner()
        raw = '```json\n{"action": "challenge", "reasoning": "wrong"}\n```'
        d = planner._parse_decision(raw)
        assert d.action == Action.CHALLENGE

    def test_json_with_prose_prefix(self):
        planner = ReActPlanner()
        raw = 'Here is my answer: {"action": "summarize", "reasoning": "lots of input"}'
        d = planner._parse_decision(raw)
        assert d.action == Action.SUMMARIZE

    def test_unknown_action_defaults_to_teach(self):
        planner = ReActPlanner()
        d = planner._parse_decision('{"action": "explode", "reasoning": "x"}')
        assert d.action == Action.TEACH

    def test_malformed_json_defaults_to_teach(self):
        planner = ReActPlanner()
        d = planner._parse_decision('not json at all')
        assert d.action == Action.TEACH

    def test_empty_input_defaults_to_teach(self):
        planner = ReActPlanner()
        d = planner._parse_decision('')
        assert d.action == Action.TEACH

    def test_uppercase_action(self):
        planner = ReActPlanner()
        d = planner._parse_decision('{"action": "TEACH"}')
        assert d.action == Action.TEACH


# ── Planner full decide flow ──────────────────────────────────────────────────

class TestPlannerDecide:
    @pytest.mark.asyncio
    async def test_classifier_calls_ollama_then_returns_decision(self):
        planner = ReActPlanner()

        async def fake_classifier(*args, **kwargs):
            yield '{"action": "ask", "reasoning": "need more context"}'

        with patch(
            "modules.react_planner.planner.ollama_client.stream_chat",
            side_effect=fake_classifier,
        ):
            ctx = ConversationContext(user_message="help with this")
            decision = await planner.decide(ctx)

        assert decision.action == Action.ASK

    @pytest.mark.asyncio
    async def test_socratic_policy_applied_after_planner(self):
        planner = ReActPlanner()

        async def fake_classifier(*args, **kwargs):
            yield '{"action": "teach", "reasoning": "clear question"}'

        with patch(
            "modules.react_planner.planner.ollama_client.stream_chat",
            side_effect=fake_classifier,
        ):
            ctx = ConversationContext(
                user_message="what is recursion?",
                mode=ConversationMode.SOCRATIC,
            )
            decision = await planner.decide(ctx)

        assert decision.action == Action.CHALLENGE

    @pytest.mark.asyncio
    async def test_classifier_failure_defaults_to_teach(self):
        planner = ReActPlanner()

        async def failing(*args, **kwargs):
            raise ConnectionError("ollama down")
            yield

        with patch(
            "modules.react_planner.planner.ollama_client.stream_chat",
            side_effect=failing,
        ):
            ctx = ConversationContext(user_message="hello?")
            decision = await planner.decide(ctx)

        assert decision.action == Action.TEACH


# ── Orchestrator ──────────────────────────────────────────────────────────────

class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_handle_message_yields_chunks(self):
        router = AIRouter()
        orch = ConversationOrchestrator(router)

        async def fake_planner_decide(self, ctx):
            return PlannerDecision(action=Action.TEACH, reasoning="test")

        async def fake_router_stream(self, msg, model_override=None, provider_override=None):
            yield "Hello "
            yield "world"

        with patch.object(ReActPlanner, "decide", fake_planner_decide):
            with patch.object(AIRouter, "stream_response", fake_router_stream):
                chunks = []
                async for chunk in orch.handle_message("test"):
                    chunks.append(chunk)

        assert "".join(chunks) == "Hello world"

    @pytest.mark.asyncio
    async def test_silent_decision_yields_nothing(self):
        router = AIRouter()
        orch = ConversationOrchestrator(router)
        orch.set_proactivity(0)

        async def fake_planner_decide(self, ctx):
            return PlannerDecision(action=Action.SILENT, reasoning="quiet")

        with patch.object(ReActPlanner, "decide", fake_planner_decide):
            chunks = [c async for c in orch.handle_message("just observing")]

        assert chunks == []

    @pytest.mark.asyncio
    async def test_interrupt_stops_stream(self):
        router = AIRouter()
        orch = ConversationOrchestrator(router)

        async def fake_planner_decide(self, ctx):
            return PlannerDecision(action=Action.TEACH)

        async def slow_stream(self, msg, model_override=None, provider_override=None):
            for i in range(10):
                await asyncio.sleep(0.05)
                yield f"chunk{i} "

        chunks: list[str] = []

        async def consume():
            with patch.object(ReActPlanner, "decide", fake_planner_decide):
                with patch.object(AIRouter, "stream_response", slow_stream):
                    async for c in orch.handle_message("test"):
                        chunks.append(c)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.15)
        orch.interrupt()
        await asyncio.wait_for(task, timeout=2.0)

        # Should stop early — not receive all 10 chunks
        assert len(chunks) < 10

    def test_set_mode(self):
        orch = ConversationOrchestrator(AIRouter())
        orch.set_mode(ConversationMode.SOCRATIC)
        assert orch.mode == ConversationMode.SOCRATIC

    def test_set_proactivity_clamps(self):
        orch = ConversationOrchestrator(AIRouter())
        orch.set_proactivity(10)
        assert orch.proactivity == 4
        orch.set_proactivity(-1)
        assert orch.proactivity == 0

    @pytest.mark.asyncio
    async def test_on_decision_callback_fires(self):
        router = AIRouter()
        orch = ConversationOrchestrator(router)
        captured: list[PlannerDecision] = []

        async def cb(d: PlannerDecision) -> None:
            captured.append(d)

        async def fake_planner_decide(self, ctx):
            return PlannerDecision(action=Action.ASK, reasoning="r")

        async def fake_router_stream(self, msg, model_override=None, provider_override=None):
            yield "Q?"

        with patch.object(ReActPlanner, "decide", fake_planner_decide):
            with patch.object(AIRouter, "stream_response", fake_router_stream):
                async for _ in orch.handle_message("hi", on_decision=cb):
                    pass

        assert len(captured) == 1
        assert captured[0].action == Action.ASK
