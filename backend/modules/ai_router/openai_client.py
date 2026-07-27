"""
OpenAI Chat Completions streaming client.

Uses Server-Sent Events (SSE) over httpx — no SDK dependency.
"""

from typing import AsyncIterator, Optional
import json
import logging
import uuid
import httpx

from modules.agent_tools.models import ToolCall, ToolDefinition
from modules.ai_router.tool_stream import Done, StreamEvent, TextDelta, ToolCallParsed

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"


async def stream_chat(
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """
    Yields text deltas from OpenAI Chat Completions in SSE streaming mode.
    Raises on auth/connection failure so caller can fall back.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "Accept":        "text/event-stream",
    }
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "stream":      True,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", f"{OPENAI_API_BASE}/chat/completions",
            json=payload, headers=headers,
        ) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    return

                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


def _to_openai_tool(t: ToolDefinition) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters_schema,
        },
    }


async def stream_chat_with_tools(
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[ToolDefinition],
    temperature: float = 0.7,
) -> AsyncIterator[StreamEvent]:
    """
    Tool-aware streaming. Yields TextDelta(s), then any ToolCallParsed(s),
    then a single Done() event for this assistant turn.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "Accept":        "text/event-stream",
    }
    payload: dict = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "stream":      True,
    }
    if tools:
        payload["tools"]       = [_to_openai_tool(t) for t in tools]
        payload["tool_choice"] = "auto"

    # Tool-call accumulators keyed by index
    pending: dict[int, dict] = {}
    finish_reason: Optional[str] = None

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", f"{OPENAI_API_BASE}/chat/completions",
            json=payload, headers=headers,
        ) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choice = (chunk.get("choices") or [{}])[0]
                delta  = choice.get("delta") or {}
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                # Natural-language deltas
                content = delta.get("content")
                if content:
                    yield TextDelta(text=content)

                # Tool-call deltas — accumulate by index
                for tc_delta in (delta.get("tool_calls") or []):
                    idx = tc_delta.get("index", 0)
                    slot = pending.setdefault(idx, {
                        "id": None, "name": "", "arguments": "",
                    })
                    if tc_delta.get("id"):
                        slot["id"] = tc_delta["id"]
                    fn = tc_delta.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

    # Emit completed tool calls (parsed)
    for idx in sorted(pending.keys()):
        slot = pending[idx]
        try:
            args = json.loads(slot["arguments"]) if slot["arguments"] else {}
        except json.JSONDecodeError:
            args = {}
        yield ToolCallParsed(call=ToolCall(
            id=slot["id"] or f"call_{uuid.uuid4().hex[:8]}",
            name=slot["name"],
            arguments=args,
        ))

    yield Done(finish_reason=finish_reason)


async def health_check(api_key: str) -> bool:
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{OPENAI_API_BASE}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return resp.status_code == 200
    except Exception:
        return False
