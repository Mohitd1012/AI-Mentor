"""
Tests for Phase 5 — Multi-provider router.

All cloud calls are mocked. No money is spent.
"""

import json
import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

from modules.ai_router import openai_client, anthropic_client
from modules.ai_router.router import AIRouter


# ── OpenAI SSE parsing ────────────────────────────────────────────────────────

class _FakeStreamResp:
    """Mocks httpx.Response.aiter_lines + context manager + raise_for_status."""
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.status_code = 200

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _patch_stream(monkeypatch, lines: list[str]):
    """Replace httpx.AsyncClient.stream with one returning given SSE lines."""
    def fake_stream(self, method, url, **kwargs):
        return _FakeStreamResp(lines)
    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)


class TestOpenAIClient:
    @pytest.mark.asyncio
    async def test_stream_parses_deltas(self, monkeypatch):
        lines = [
            'data: {"choices":[{"delta":{"content":"Hello "}}]}',
            'data: {"choices":[{"delta":{"content":"world"}}]}',
            'data: [DONE]',
        ]
        _patch_stream(monkeypatch, lines)

        chunks = []
        async for c in openai_client.stream_chat("sk-test", "gpt-4o-mini",
                                                   [{"role": "user", "content": "hi"}]):
            chunks.append(c)
        assert "".join(chunks) == "Hello world"

    @pytest.mark.asyncio
    async def test_stream_skips_malformed_lines(self, monkeypatch):
        lines = [
            'not-an-sse-line',
            'data: not-json{',
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            'data: [DONE]',
        ]
        _patch_stream(monkeypatch, lines)
        chunks = [c async for c in openai_client.stream_chat("sk-test", "gpt-4o-mini", [])]
        assert chunks == ["ok"]

    @pytest.mark.asyncio
    async def test_stream_skips_empty_deltas(self, monkeypatch):
        lines = [
            'data: {"choices":[{"delta":{}}]}',
            'data: {"choices":[{"delta":{"content":"x"}}]}',
            'data: [DONE]',
        ]
        _patch_stream(monkeypatch, lines)
        chunks = [c async for c in openai_client.stream_chat("sk-test", "gpt-4o-mini", [])]
        assert chunks == ["x"]


# ── Anthropic SSE parsing ─────────────────────────────────────────────────────

class TestAnthropicClient:
    @pytest.mark.asyncio
    async def test_stream_parses_text_deltas(self, monkeypatch):
        lines = [
            'data: {"type":"message_start","message":{}}',
            'data: {"type":"content_block_start"}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello "}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"world"}}',
            'data: {"type":"content_block_stop"}',
            'data: {"type":"message_stop"}',
        ]
        _patch_stream(monkeypatch, lines)
        chunks = [c async for c in anthropic_client.stream_chat("sk-ant", "claude-x", [])]
        assert "".join(chunks) == "Hello world"

    @pytest.mark.asyncio
    async def test_ignores_non_text_deltas(self, monkeypatch):
        lines = [
            'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{}"}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"text"}}',
            'data: {"type":"message_stop"}',
        ]
        _patch_stream(monkeypatch, lines)
        chunks = [c async for c in anthropic_client.stream_chat("sk-ant", "claude-x", [])]
        assert chunks == ["text"]

    def test_split_system_messages(self):
        msgs = [
            {"role": "system",    "content": "You are helpful"},
            {"role": "system",    "content": "Be concise"},
            {"role": "user",      "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        system, conv = anthropic_client._split_system_messages(msgs)
        assert "helpful" in system
        assert "concise" in system
        assert len(conv) == 2
        assert all(m["role"] != "system" for m in conv)


# ── Router waterfall ──────────────────────────────────────────────────────────

class TestRouterWaterfall:
    @pytest.mark.asyncio
    async def test_ollama_used_by_default(self):
        router = AIRouter()

        async def fake_ollama(*args, **kwargs):
            yield "ollama-says-hi"

        with patch("modules.ai_router.router.ollama_client.stream_chat", side_effect=fake_ollama):
            chunks = [c async for c in router.stream_response("hi")]
        assert "".join(chunks) == "ollama-says-hi"

    @pytest.mark.asyncio
    async def test_provider_override_routes_to_openai(self):
        router = AIRouter()
        router.settings.openai_api_key = "sk-test"

        async def fake_openai(*args, **kwargs):
            yield "openai-says-hi"

        with patch("modules.ai_router.router.openai_client.stream_chat", side_effect=fake_openai):
            chunks = [c async for c in router.stream_response("hi", provider_override="openai")]
        assert "".join(chunks) == "openai-says-hi"

    @pytest.mark.asyncio
    async def test_falls_back_when_first_provider_fails(self):
        router = AIRouter()
        router.settings.openai_api_key = "sk-test"
        router.set_preferred_provider("openai")

        async def failing_openai(*args, **kwargs):
            raise ConnectionError("openai down")
            yield

        async def good_ollama(*args, **kwargs):
            yield "fallback-ok"

        with patch("modules.ai_router.router.openai_client.stream_chat", side_effect=failing_openai):
            with patch("modules.ai_router.router.ollama_client.stream_chat", side_effect=good_ollama):
                chunks = [c async for c in router.stream_response("hi")]
        assert "".join(chunks) == "fallback-ok"

    @pytest.mark.asyncio
    async def test_missing_api_key_is_skipped(self):
        router = AIRouter()
        router.settings.openai_api_key = ""    # no key
        router.set_preferred_provider("openai")

        async def ollama_responds(*args, **kwargs):
            yield "from-ollama"

        with patch("modules.ai_router.router.ollama_client.stream_chat", side_effect=ollama_responds):
            chunks = [c async for c in router.stream_response("hi")]
        assert "".join(chunks) == "from-ollama"

    def test_get_available_providers_only_ollama_by_default(self):
        router = AIRouter()
        router.settings.openai_api_key = ""
        router.settings.anthropic_api_key = ""
        assert router.get_available_providers() == ["ollama"]

    def test_get_available_providers_with_keys(self):
        router = AIRouter()
        router.settings.openai_api_key = "sk-x"
        router.settings.anthropic_api_key = "sk-ant-x"
        avail = router.get_available_providers()
        assert "ollama" in avail
        assert "openai" in avail
        assert "anthropic" in avail

    def test_set_preferred_rejects_unknown(self):
        router = AIRouter()
        with pytest.raises(ValueError):
            router.set_preferred_provider("groq")

    def test_set_preferred_accepts_none(self):
        router = AIRouter()
        router.set_preferred_provider(None)
        assert router.preferred_provider is None

    def test_provider_order_puts_override_first(self):
        router = AIRouter()
        order = router._provider_order("anthropic")
        assert order[0] == "anthropic"
        assert "ollama" in order   # still in waterfall as fallback

    def test_provider_order_default_uses_settings(self):
        router = AIRouter()
        order = router._provider_order(None)
        assert order == list(router.settings.ai_provider_priority)
