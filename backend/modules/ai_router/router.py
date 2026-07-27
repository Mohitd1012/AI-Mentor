"""
AI Router — provider waterfall with per-call override.

Provider priority (configurable in config.py): ollama → openai → anthropic.
Each provider is independently optional; missing API keys silently disable.
"""

from typing import AsyncIterator, Optional
import logging

from config import get_settings
from modules.agent_tools.models import ToolDefinition
from modules.ai_router import ollama_client, openai_client, anthropic_client
from modules.ai_router.tool_stream import Done, StreamEvent

logger = logging.getLogger(__name__)


class ConversationHistory:
    def __init__(self, max_turns: int = 20) -> None:
        self._max = max_turns
        self._messages: list[dict] = []

    def add(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
        if len(self._messages) > self._max * 2:
            self._messages = self._messages[-(self._max * 2):]

    def to_list(self) -> list[dict]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()


_BASE_SYSTEM_PROMPT = (
    "You are a senior AI mentor and pair programmer. "
    "You observe the user's screen and assist them in real time. "
    "Be concise, direct, and insightful. "
    "Ask clarifying questions when needed. "
    "Challenge assumptions constructively. "
    "Keep responses focused and practical."
)


class AIRouter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._history = ConversationHistory()
        self._base_prompt = _BASE_SYSTEM_PROMPT
        self._screen_context_block = ""
        # Currently-selected provider override ("ollama" | "openai" | "anthropic" | None)
        self._preferred_provider: Optional[str] = None
        # Optional model override applied when no per-call model is given.
        # Roles set this via `apply_role()`; the picker UI can override per call.
        self._preferred_model: Optional[str] = None

    # ── Public ────────────────────────────────────────────────────────────────

    def update_screen_context(self, context_block: str) -> None:
        self._screen_context_block = context_block

    def set_preferred_provider(self, provider: Optional[str]) -> None:
        """Override the default provider priority. None = use settings order."""
        if provider not in (None, "ollama", "openai", "anthropic"):
            raise ValueError(f"Unknown provider: {provider}")
        self._preferred_provider = provider
        logger.info("[router] preferred provider → %s", provider or "auto")

    @property
    def preferred_provider(self) -> Optional[str]:
        return self._preferred_provider

    def set_preferred_model(self, model: Optional[str]) -> None:
        """
        Default model used when no per-call override is supplied.
        Roles set this in `apply_role()`. None = fall back to provider's
        settings.<provider>_default_model.
        """
        self._preferred_model = model
        logger.info("[router] preferred model → %s", model or "auto")

    @property
    def preferred_model(self) -> Optional[str]:
        return self._preferred_model

    def get_available_providers(self) -> list[str]:
        """Returns providers that have credentials/config to actually run."""
        out = ["ollama"]   # always available locally
        if self.settings.openai_api_key:
            out.append("openai")
        if self.settings.anthropic_api_key:
            out.append("anthropic")
        return out

    # ── Streaming entry point ─────────────────────────────────────────────────

    async def stream_response(
        self,
        user_message: str,
        model_override: Optional[str] = None,
        provider_override: Optional[str] = None,
    ) -> AsyncIterator[str]:
        self._history.add("user", user_message)

        system = self._build_system_prompt()
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history.to_list()[:-1])
        messages.append({"role": "user", "content": user_message})

        full_response = ""
        provider_used: Optional[str] = None

        for provider in self._provider_order(provider_override):
            try:
                async for chunk in self._call_provider(provider, model_override, messages):
                    full_response += chunk
                    yield chunk
                provider_used = provider
                break  # success → stop waterfall
            except NotImplementedError:
                continue
            except Exception as exc:
                logger.warning("[router] provider=%s failed: %s — trying next",
                               provider, exc)
                continue
        else:
            yield (
                "⚠️ No AI provider is available. "
                "Make sure Ollama is running (`ollama serve`) or set "
                "OPENAI_API_KEY / ANTHROPIC_API_KEY in backend/.env."
            )
            return

        if provider_used:
            logger.info("[router] served via %s", provider_used)
        if full_response:
            self._history.add("assistant", full_response)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _provider_order(self, per_call_override: Optional[str]) -> list[str]:
        """Compute the waterfall: per-call override → instance preference → settings."""
        override = per_call_override or self._preferred_provider
        if override:
            base = [override]
            for p in self.settings.ai_provider_priority:
                if p != override:
                    base.append(p)
            return base
        return list(self.settings.ai_provider_priority)

    async def _call_provider(
        self,
        provider: str,
        model_override: Optional[str],
        messages: list[dict],
    ) -> AsyncIterator[str]:
        s = self.settings

        # Effective model: per-call override → instance preference → settings default
        prefer = self._preferred_model

        if provider == "ollama":
            model = model_override or prefer or s.ollama_default_model
            logger.info("[router] → ollama model=%s", model)
            async for chunk in ollama_client.stream_chat(
                s.ollama_base_url, model, messages,
            ):
                yield chunk
            return

        if provider == "openai":
            if not s.openai_api_key:
                raise NotImplementedError("OpenAI key not configured")
            model = model_override or prefer or s.openai_default_model
            logger.info("[router] → openai model=%s", model)
            async for chunk in openai_client.stream_chat(
                s.openai_api_key, model, messages,
            ):
                yield chunk
            return

        if provider == "anthropic":
            if not s.anthropic_api_key:
                raise NotImplementedError("Anthropic key not configured")
            model = model_override or prefer or s.anthropic_default_model
            logger.info("[router] → anthropic model=%s", model)
            async for chunk in anthropic_client.stream_chat(
                s.anthropic_api_key, model, messages,
            ):
                yield chunk
            return

        raise NotImplementedError(f"Unknown provider: {provider}")

    # ── Tool-aware streaming (Agentic Tier 1) ─────────────────────────────────

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[ToolDefinition],
        model_override: Optional[str] = None,
        provider_override: Optional[str] = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Like stream_response but emits provider-neutral tool-call events.
        Does NOT touch the router's history — the caller manages it because
        agent turns may include synthetic tool-result messages.
        """
        for provider in self._provider_order(provider_override):
            try:
                async for evt in self._call_provider_with_tools(
                    provider, model_override, messages, tools,
                ):
                    yield evt
                return  # success → stop waterfall
            except NotImplementedError:
                continue
            except Exception as exc:
                logger.warning("[router/tools] provider=%s failed: %s — trying next",
                               provider, exc)
                continue

        # All providers failed
        yield Done(finish_reason="error")

    async def _call_provider_with_tools(
        self,
        provider: str,
        model_override: Optional[str],
        messages: list[dict],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        s = self.settings
        prefer = self._preferred_model

        if provider == "ollama":
            model = model_override or prefer or s.ollama_default_model
            logger.info("[router/tools] → ollama model=%s tools=%d", model, len(tools))
            async for evt in ollama_client.stream_chat_with_tools(
                s.ollama_base_url, model, messages, tools,
            ):
                yield evt
            return

        if provider == "openai":
            if not s.openai_api_key:
                raise NotImplementedError("OpenAI key not configured")
            model = model_override or prefer or s.openai_default_model
            logger.info("[router/tools] → openai model=%s tools=%d", model, len(tools))
            async for evt in openai_client.stream_chat_with_tools(
                s.openai_api_key, model, messages, tools,
            ):
                yield evt
            return

        if provider == "anthropic":
            if not s.anthropic_api_key:
                raise NotImplementedError("Anthropic key not configured")
            model = model_override or prefer or s.anthropic_default_model
            logger.info("[router/tools] → anthropic model=%s tools=%d", model, len(tools))
            async for evt in anthropic_client.stream_chat_with_tools(
                s.anthropic_api_key, model, messages, tools,
            ):
                yield evt
            return

        raise NotImplementedError(f"Unknown provider: {provider}")

    def _build_system_prompt(self) -> str:
        if self._screen_context_block:
            return f"{self._base_prompt}\n\n{self._screen_context_block}"
        return self._base_prompt

    # ── Misc ─────────────────────────────────────────────────────────────────

    def clear_history(self) -> None:
        self._history.clear()

    def set_base_prompt(self, prompt: str) -> None:
        self._base_prompt = prompt
