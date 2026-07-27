"""
WebSocket handler tests using FastAPI's TestClient.
"""

import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app


async def fake_stream(user_msg, model_override=None, provider_override=None):
    yield "chunk1 "
    yield "chunk2"


async def fake_planner_decide(self, ctx):
    from modules.react_planner.models import Action, PlannerDecision
    return PlannerDecision(action=Action.TEACH, reasoning="test")


async def fake_stream_with_tools(self, messages, tools,
                                  model_override=None, provider_override=None):
    """Mock for the agent-loop path used by /ws chat now."""
    from modules.ai_router.tool_stream import Done, TextDelta
    yield TextDelta(text="chunk1 ")
    yield TextDelta(text="chunk2")
    yield Done()


class TestWebSocketHandler:
    def test_ping_pong(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_text(json.dumps({"type": "ping"}))
                data = json.loads(ws.receive_text())
                assert data["type"] == "pong"

    def test_chat_returns_chunks(self):
        # The WS handler now uses the agent loop, which calls
        # AIRouter.stream_with_tools. Patch that.
        with patch("modules.ai_router.router.AIRouter.stream_with_tools",
                   fake_stream_with_tools), \
             patch("modules.react_planner.planner.ReActPlanner.decide",
                   fake_planner_decide), \
             patch("modules.ai_router.router.AIRouter.stream_response",
                   side_effect=fake_stream):
            with TestClient(app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.send_text(json.dumps({
                        "type": "chat",
                        "id": "test-1",
                        "content": "hello",
                    }))

                    messages = []
                    # Collect: status(thinking) + chunks + status(idle)
                    for _ in range(10):
                        raw = ws.receive_text()
                        msg = json.loads(raw)
                        messages.append(msg)
                        if msg.get("type") == "status" and msg.get("state") == "idle":
                            break

                    types = [m["type"] for m in messages]
                    assert "chunk" in types
                    assert "status" in types

                    chunk_contents = [
                        m["content"] for m in messages
                        if m["type"] == "chunk" and m.get("content")
                    ]
                    assert "chunk1 " in chunk_contents or "chunk2" in chunk_contents

    def test_invalid_json_returns_error(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_text("not valid json{{{")
                data = json.loads(ws.receive_text())
                assert data["type"] == "error"

    def test_health_endpoint(self):
        with patch(
            "main.ollama_client.health_check",
            return_value=True,
        ):
            with TestClient(app) as client:
                resp = client.get("/health")
                assert resp.status_code == 200
                body = resp.json()
                assert body["status"] == "ok"
