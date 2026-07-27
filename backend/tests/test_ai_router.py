"""
Integration tests for the AI router and Ollama client.

Requires a running Ollama instance with at least one model available.
Skip with: pytest -m "not integration"
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from modules.ai_router.router import AIRouter, ConversationHistory
from modules.ai_router import ollama_client


# ── Unit tests ──────────────────────────────────────────────────────────────

class TestConversationHistory:
    def test_add_and_retrieve(self):
        h = ConversationHistory(max_turns=2)
        h.add("user", "hello")
        h.add("assistant", "hi")
        assert len(h.to_list()) == 2

    def test_max_turns_trim(self):
        h = ConversationHistory(max_turns=2)
        for i in range(6):
            h.add("user" if i % 2 == 0 else "assistant", f"msg {i}")
        assert len(h.to_list()) <= 4  # max_turns * 2

    def test_clear(self):
        h = ConversationHistory()
        h.add("user", "test")
        h.clear()
        assert h.to_list() == []


class TestAIRouter:
    @pytest.mark.asyncio
    async def test_stream_uses_ollama_by_default(self):
        async def fake_stream(base_url, model, messages):
            yield "Hello "
            yield "world"

        with patch(
            "modules.ai_router.router.ollama_client.stream_chat",
            side_effect=fake_stream,
        ):
            router = AIRouter()
            chunks = []
            async for chunk in router.stream_response("test"):
                chunks.append(chunk)

        assert "".join(chunks) == "Hello world"

    @pytest.mark.asyncio
    async def test_history_accumulates(self):
        async def fake_stream(base_url, model, messages):
            yield "response"

        with patch(
            "modules.ai_router.router.ollama_client.stream_chat",
            side_effect=fake_stream,
        ):
            router = AIRouter()
            async for _ in router.stream_response("first message"):
                pass

        # History should have user + assistant messages
        assert len(router._history.to_list()) == 2

    @pytest.mark.asyncio
    async def test_fallback_message_when_all_providers_fail(self):
        async def failing_stream(*args, **kwargs):
            raise ConnectionError("provider down")
            yield  # make it an async generator

        # Force all three providers to fail so we hit the final fallback
        with patch("modules.ai_router.router.ollama_client.stream_chat",
                   side_effect=failing_stream), \
             patch("modules.ai_router.router.openai_client.stream_chat",
                   side_effect=failing_stream), \
             patch("modules.ai_router.router.anthropic_client.stream_chat",
                   side_effect=failing_stream):
            router = AIRouter()
            # Pretend all keys are configured so each provider is attempted
            router.settings.openai_api_key = "sk-test"
            router.settings.anthropic_api_key = "sk-ant-test"
            chunks = []
            async for chunk in router.stream_response("hello"):
                chunks.append(chunk)

        result = "".join(chunks)
        assert "No AI provider" in result or "⚠️" in result

    def test_set_system_prompt(self):
        router = AIRouter()
        router.set_base_prompt("You are a Kubernetes expert.")
        assert "Kubernetes" in router._base_prompt

    def test_clear_history(self):
        router = AIRouter()
        router._history.add("user", "hi")
        router.clear_history()
        assert router._history.to_list() == []


# ── Integration tests (require live Ollama) ─────────────────────────────────

@pytest.mark.integration
class TestOllamaIntegration:
    @pytest.mark.asyncio
    async def test_health_check(self):
        ok = await ollama_client.health_check("http://localhost:11434")
        assert ok, "Ollama must be running for integration tests"

    @pytest.mark.asyncio
    async def test_list_models(self):
        models = await ollama_client.list_models("http://localhost:11434")
        assert isinstance(models, list)

    @pytest.mark.asyncio
    async def test_stream_chat_produces_output(self):
        chunks = []
        async for chunk in ollama_client.stream_chat(
            "http://localhost:11434",
            "qwen2.5:3b",
            [{"role": "user", "content": "Say the word 'hello' only."}],
        ):
            chunks.append(chunk)
        assert len(chunks) > 0
        assert any(c.strip() for c in chunks)
