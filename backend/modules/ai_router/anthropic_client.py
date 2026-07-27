"""
Anthropic Claude Messages streaming client.

Uses SSE over httpx — no SDK dependency.
Reference: https://docs.anthropic.com/en/api/messages-streaming
"""

from typing import AsyncIterator, Optional
import json
import logging
import uuid
import httpx

from modules.agent_tools.models import ToolCall, ToolDefinition
from modules.ai_router.tool_stream import Done, StreamEvent, TextDelta, ToolCallParsed

logger = logging.getLogger(__name__)

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION  = "2023-06-01"


def _split_system_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """
    Anthropic requires `system` as a top-level field, not in messages.
    Pull out any system messages and concatenate them.
    """
    system_parts: list[str] = []
    conv: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            conv.append(m)
    return "\n\n".join(system_parts), conv


async def stream_chat(
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """
    Yields text deltas from Anthropic Messages streaming endpoint.
    """
    system, conv = _split_system_messages(messages)

    headers = {
        "x-api-key":         api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type":      "application/json",
        "Accept":            "text/event-stream",
    }
    payload: dict = {
        "model":       model,
        "messages":    conv,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "stream":      True,
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", f"{ANTHROPIC_API_BASE}/messages",
            json=payload, headers=headers,
        ) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                ev_type = event.get("type")
                if ev_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if text:
                            yield text
                elif ev_type == "message_stop":
                    return


def _to_anthropic_tool(t: ToolDefinition) -> dict:
    return {
        "name": t.name,
        "description": t.description,
        "input_schema": t.parameters_schema,
    }


async def stream_chat_with_tools(
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[ToolDefinition],
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> AsyncIterator[StreamEvent]:
    system, conv = _split_system_messages(messages)

    headers = {
        "x-api-key":         api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type":      "application/json",
        "Accept":            "text/event-stream",
    }
    payload: dict = {
        "model":       model,
        "messages":    conv,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "stream":      True,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [_to_anthropic_tool(t) for t in tools]

    # State per content block index
    blocks: dict[int, dict] = {}
    stop_reason: Optional[str] = None

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", f"{ANTHROPIC_API_BASE}/messages",
            json=payload, headers=headers,
        ) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")

                if etype == "content_block_start":
                    idx = event.get("index", 0)
                    cb  = event.get("content_block") or {}
                    blocks[idx] = {
                        "type": cb.get("type"),
                        "id":   cb.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        "name": cb.get("name", ""),
                        "json": "",
                    }

                elif etype == "content_block_delta":
                    idx   = event.get("index", 0)
                    delta = event.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        text = delta.get("text")
                        if text:
                            yield TextDelta(text=text)
                    elif dtype == "input_json_delta":
                        slot = blocks.setdefault(idx, {"type": "tool_use", "id": "",
                                                       "name": "", "json": ""})
                        slot["json"] += delta.get("partial_json", "")

                elif etype == "message_delta":
                    delta = event.get("delta") or {}
                    if delta.get("stop_reason"):
                        stop_reason = delta["stop_reason"]

                elif etype == "message_stop":
                    break

    # Emit assembled tool calls
    for idx in sorted(blocks.keys()):
        slot = blocks[idx]
        if slot.get("type") != "tool_use":
            continue
        try:
            args = json.loads(slot["json"]) if slot["json"] else {}
        except json.JSONDecodeError:
            args = {}
        yield ToolCallParsed(call=ToolCall(
            id=slot["id"], name=slot["name"], arguments=args,
        ))

    yield Done(finish_reason=stop_reason)


async def health_check(api_key: str) -> bool:
    """Minimal completion call to verify the key works."""
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{ANTHROPIC_API_BASE}/messages",
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "Content-Type":      "application/json",
                },
                json={
                    "model":      "claude-3-5-haiku-20241022",
                    "max_tokens": 1,
                    "messages":   [{"role": "user", "content": "hi"}],
                },
            )
            return resp.status_code in (200, 201)
    except Exception:
        return False
