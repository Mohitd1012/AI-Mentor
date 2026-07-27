"""
Tests for the agent loop in ConversationOrchestrator.run_agent_turn.

We mock the router's stream_with_tools so we can script tool-call sequences
without hitting any real LLM.
"""

import pytest
from pathlib import Path
from typing import AsyncIterator

from modules.agent_tools import ToolRegistry, ToolCall, ToolDefinition, ToolResult
from modules.agent_tools.builtins import SaveMemoryTool, SearchMemoryTool
from modules.ai_router.router import AIRouter
from modules.ai_router.tool_stream import Done, StreamEvent, TextDelta, ToolCallParsed
from modules.memory_manager import MemoryManager, MemoryKind
from modules.react_planner import ConversationOrchestrator
from modules.react_planner.orchestrator import MAX_TOOL_ROUNDS


@pytest.fixture
def tmp_mem(tmp_path: Path):
    return MemoryManager(
        sqlite_path=tmp_path / "m.db",
        chroma_dir=tmp_path / "c",
        extraction_enabled=False,
    )


@pytest.fixture
def tools(tmp_mem):
    reg = ToolRegistry()
    reg.register(SaveMemoryTool(tmp_mem))
    reg.register(SearchMemoryTool(tmp_mem))
    return reg


def make_router_with_scripted_responses(responses: list[list[StreamEvent]]) -> AIRouter:
    """
    Returns an AIRouter whose stream_with_tools yields each scripted response
    in sequence, one per agent-loop round.
    """
    router = AIRouter()
    call_count = {"n": 0}

    async def fake_stream(messages, tools, model_override=None, provider_override=None):
        idx = call_count["n"]
        call_count["n"] += 1
        events = responses[idx] if idx < len(responses) else [Done()]
        for evt in events:
            yield evt

    router.stream_with_tools = fake_stream
    return router


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_simple_text_response_no_tools(self, tmp_mem, tools):
        router = make_router_with_scripted_responses([
            [TextDelta(text="Hello"), TextDelta(text=" world."), Done()],
        ])
        orch = ConversationOrchestrator(router, memory=tmp_mem, tools=tools)
        events = [e async for e in orch.run_agent_turn("hi")]
        # All chunks should carry content; final has done=True
        text_chunks = [e for e in events if e["type"] == "chunk" and e.get("content")]
        assert any(e["content"] == "Hello" for e in text_chunks)
        assert any(e["content"] == " world." for e in text_chunks)
        assert any(e["type"] == "chunk" and e.get("done") for e in events)
        # No tool calls expected
        assert not any(e["type"] == "tool_call" for e in events)

    @pytest.mark.asyncio
    async def test_single_tool_call_then_final_answer(self, tmp_mem, tools):
        router = make_router_with_scripted_responses([
            # Round 1: model asks to save a memory
            [
                TextDelta(text="Let me note that down."),
                ToolCallParsed(call=ToolCall(
                    id="call-1", name="save_memory",
                    arguments={"content": "User prefers brief answers",
                                "kind": "preference"},
                )),
                Done(),
            ],
            # Round 2: model produces final reply
            [
                TextDelta(text="Got it — I'll keep responses short."),
                Done(),
            ],
        ])
        orch = ConversationOrchestrator(router, memory=tmp_mem, tools=tools)
        events = [e async for e in orch.run_agent_turn("be brief")]

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "save_memory"
        assert len(tool_results) == 1
        assert tool_results[0]["is_error"] is False
        # Memory was persisted
        assert any(m.content == "User prefers brief answers"
                    for m in tmp_mem.list_memories())

    @pytest.mark.asyncio
    async def test_max_rounds_cap(self, tmp_mem, tools):
        """Model keeps asking for tools forever — loop must stop at MAX_TOOL_ROUNDS."""
        # Each round emits the same tool call
        looping = [
            [ToolCallParsed(call=ToolCall(
                id=f"call-{i}", name="search_memory", arguments={"query": "x"},
            )), Done()]
            for i in range(MAX_TOOL_ROUNDS + 3)
        ]
        router = make_router_with_scripted_responses(looping)
        orch = ConversationOrchestrator(router, memory=tmp_mem, tools=tools)
        events = [e async for e in orch.run_agent_turn("loop please")]

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        # Stops at MAX_TOOL_ROUNDS calls (one per round)
        assert len(tool_calls) == MAX_TOOL_ROUNDS

    @pytest.mark.asyncio
    async def test_tool_result_fed_back_to_model(self, tmp_mem, tools):
        """The router should receive a 'tool' message in round 2's messages."""
        captured_messages: list[list[dict]] = []

        async def capture(messages, tools_, model_override=None, provider_override=None):
            captured_messages.append([dict(m) for m in messages])
            if len(captured_messages) == 1:
                yield ToolCallParsed(call=ToolCall(
                    id="c1", name="search_memory", arguments={"query": "x"},
                ))
                yield Done()
            else:
                yield TextDelta(text="done")
                yield Done()

        router = AIRouter()
        router.stream_with_tools = capture
        orch = ConversationOrchestrator(router, memory=tmp_mem, tools=tools)
        _ = [e async for e in orch.run_agent_turn("hi")]

        # Round 2's messages should include a 'tool' role message
        round_2_msgs = captured_messages[1]
        roles = [m["role"] for m in round_2_msgs]
        assert "tool" in roles
        tool_msg = next(m for m in round_2_msgs if m["role"] == "tool")
        assert tool_msg["tool_call_id"] == "c1"

    @pytest.mark.asyncio
    async def test_unknown_tool_does_not_crash(self, tmp_mem, tools):
        router = make_router_with_scripted_responses([
            [ToolCallParsed(call=ToolCall(
                id="c", name="does_not_exist", arguments={},
            )), Done()],
            [TextDelta(text="recovered"), Done()],
        ])
        orch = ConversationOrchestrator(router, memory=tmp_mem, tools=tools)
        events = [e async for e in orch.run_agent_turn("call something missing")]
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert tool_results[0]["is_error"] is True

    @pytest.mark.asyncio
    async def test_fallback_when_no_tools_registered(self, tmp_mem):
        """If the registry is empty, run_agent_turn falls back to handle_message."""
        empty_tools = ToolRegistry()
        router = AIRouter()

        # Mock the planner so we don't hit ollama
        from modules.react_planner.models import Action, PlannerDecision
        from unittest.mock import patch

        async def fake_decide(self, ctx):
            return PlannerDecision(action=Action.TEACH)

        async def fake_stream(self, msg, model_override=None, provider_override=None):
            yield "fallback ok"

        with patch("modules.react_planner.planner.ReActPlanner.decide", fake_decide):
            with patch("modules.ai_router.router.AIRouter.stream_response", fake_stream):
                orch = ConversationOrchestrator(router, memory=tmp_mem,
                                                 tools=empty_tools)
                events = [e async for e in orch.run_agent_turn("hi")]
                text = "".join(
                    e.get("content", "") for e in events
                    if e["type"] == "chunk" and not e.get("done")
                )
                assert "fallback ok" in text
