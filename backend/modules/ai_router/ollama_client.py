"""
Ollama streaming client.

Sends a chat completion request to the local Ollama server and yields
text chunks as they arrive via Server-Sent Events.
"""

from typing import AsyncIterator, Optional
import httpx
import json
import logging
import uuid

from modules.agent_tools.models import ToolCall, ToolDefinition
from modules.ai_router.tool_stream import Done, StreamEvent, TextDelta, ToolCallParsed

logger = logging.getLogger(__name__)


async def stream_chat(
    base_url: str,
    model: str,
    messages: list[dict],
) -> AsyncIterator[str]:
    """
    Yields text chunks from Ollama /api/chat (streaming).
    Raises on connection failure so the caller can fallback.
    """
    url = f"{base_url}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                if not raw_line.strip():
                    continue
                try:
                    data = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                content = data.get("message", {}).get("content", "")
                if content:
                    yield content

                if data.get("done", False):
                    return


async def list_models(base_url: str) -> list[str]:
    """Returns names of models available in the local Ollama instance."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception as exc:
        logger.warning("Could not list Ollama models: %s", exc)
        return []


def _to_ollama_tool(t: ToolDefinition) -> dict:
    """Ollama uses the OpenAI tool schema (function-style)."""
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters_schema,
        },
    }


async def stream_chat_with_tools(
    base_url: str,
    model: str,
    messages: list[dict],
    tools: list[ToolDefinition],
) -> AsyncIterator[StreamEvent]:
    """
    Tool-aware streaming for Ollama. Requires a model with tool support
    (qwen2.5, llama3.1, mistral-nemo, etc).
    """
    url = f"{base_url}/api/chat"
    payload: dict = {
        "model":    model,
        "messages": messages,
        "stream":   True,
    }
    if tools:
        payload["tools"] = [_to_ollama_tool(t) for t in tools]

    parsed_calls: list[ToolCall] = []
    finish_reason: Optional[str] = None

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                if not raw_line.strip():
                    continue
                try:
                    data = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                msg = data.get("message") or {}
                content = msg.get("content")
                if content:
                    yield TextDelta(text=content)

                # Ollama emits tool_calls as a list on the message
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments")
                    # Ollama returns arguments either as dict or json string
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    parsed_calls.append(ToolCall(
                        id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        name=fn.get("name", ""),
                        arguments=args or {},
                    ))

                if data.get("done"):
                    finish_reason = data.get("done_reason")
                    break

    for call in parsed_calls:
        yield ToolCallParsed(call=call)
    yield Done(finish_reason=finish_reason)


async def health_check(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(base_url)
            return resp.status_code == 200
    except Exception:
        return False
