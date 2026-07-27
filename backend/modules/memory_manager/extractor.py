"""
Fact extractor — calls a small LLM to distill durable memories from a turn.

We use the same Ollama instance and a fast small model. The extractor is
fire-and-forget from the orchestrator's perspective — it returns 0+ memories
and the manager persists them.
"""

import json
import logging
import re
from typing import Optional

from config import get_settings
from modules.ai_router import ollama_client
from modules.memory_manager.models import Memory, MemoryKind

logger = logging.getLogger(__name__)


EXTRACTOR_SYSTEM = """You extract DURABLE facts about the user from a single
conversation turn. Output JSON only.

Schema:
[
  {"kind": "preference|fact|goal|project|note", "content": "<one short sentence>"}
]

Rules:
  - Only include facts that will be useful in FUTURE conversations.
  - Skip transient details, jokes, restated questions, fluff.
  - Each fact must be self-contained (no pronouns like "this", "that").
  - Quotes, code, and questions don't go in memory.
  - Output `[]` if nothing durable was learned.
  - Maximum 3 facts per turn."""


_JSON_ARRAY_RE = re.compile(r'\[[^\[\]]*(?:\{[^{}]*\}[^\[\]]*)*\]', re.DOTALL)


async def extract_memories(
    user_msg: str,
    assistant_msg: str,
    role_id: Optional[str] = None,
) -> list[Memory]:
    """Returns a list of new Memory objects. Empty on failure."""
    settings = get_settings()
    model = "qwen2.5:3b"   # small + fast

    prompt = (
        f"USER: {user_msg.strip()[:1000]}\n"
        f"ASSISTANT: {assistant_msg.strip()[:1000]}\n\n"
        "Extract durable memories as JSON array. Output JSON only."
    )

    messages = [
        {"role": "system", "content": EXTRACTOR_SYSTEM},
        {"role": "user",   "content": prompt},
    ]

    chunks: list[str] = []
    try:
        async for chunk in ollama_client.stream_chat(
            settings.ollama_base_url, model, messages
        ):
            chunks.append(chunk)
            joined = "".join(chunks)
            # Stop early once we have a balanced JSON array
            if joined.count("[") > 0 and joined.count("[") == joined.count("]"):
                break
    except Exception as exc:
        logger.warning("[extractor] LLM call failed: %s", exc)
        return []

    raw = "".join(chunks).strip()
    return _parse_memories(raw, role_id)


def _parse_memories(raw: str, role_id: Optional[str]) -> list[Memory]:
    if not raw:
        return []

    # Find the first balanced JSON array in the output
    match = _JSON_ARRAY_RE.search(raw)
    candidate = match.group(0) if match else raw

    try:
        items = json.loads(candidate)
    except json.JSONDecodeError:
        logger.debug("[extractor] could not parse JSON: %.120s", raw)
        return []

    if not isinstance(items, list):
        return []

    out: list[Memory] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content or len(content) < 5 or len(content) > 280:
            continue
        kind_str = str(item.get("kind", "note")).lower().strip()
        try:
            kind = MemoryKind(kind_str)
        except ValueError:
            kind = MemoryKind.NOTE
        out.append(Memory(
            content=content,
            kind=kind,
            source="auto",
            role_id=role_id,
        ))
    return out
