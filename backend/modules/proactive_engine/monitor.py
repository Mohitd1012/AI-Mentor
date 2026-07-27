"""
ProactiveMonitor — subscribes to ScreenCaptureEngine, runs trigger detectors,
respects cooldown + snooze, and fires a callback when a TriggerEvent occurs.

Lifecycle:
  • `attach(capture_engine)` adds a listener; auto-runs on every screen update.
  • `set_proactivity(level)` adjusts behaviour profile at runtime.
  • `snooze(seconds)` silences ALL triggers for a window.
  • `on_trigger(cb)` registers the async callback called per fire.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from modules.proactive_engine.models import (
    AGENT_MODE_CONFIG, LEVELS, LevelConfig, TriggerEvent, TriggerKind,
)
from modules.proactive_engine.triggers import (
    TriggerState, _tokens, detect_context_shift, detect_error_loop,
    detect_idle, detect_screen_change, detect_stuck, update_state,
)
from modules.screen_capture import ScreenCaptureEngine, ScreenContext

logger = logging.getLogger(__name__)

TriggerCallback = Callable[[TriggerEvent], Awaitable[None]]


class ProactiveMonitor:
    def __init__(self, proactivity: int = 2) -> None:
        self._level     = max(0, min(4, proactivity))
        self._state     = TriggerState()
        self._last_fire = 0.0
        self._snooze_until = 0.0
        self._on_trigger: Optional[TriggerCallback] = None
        self._agent_mode = False

    def _active_config(self) -> LevelConfig:
        """Returns the LevelConfig that's currently in effect."""
        return AGENT_MODE_CONFIG if self._agent_mode else LEVELS[self._level]

    def set_agent_mode(self, enabled: bool) -> None:
        """
        Continuous-narration mode: the AI comments on every meaningful screen
        change with ~25s cooldown. Overrides the proactivity-level config.
        """
        self._agent_mode = bool(enabled)
        logger.info("[proactive] agent_mode → %s", self._agent_mode)
        # Re-seed the token bag so the next change is judged against current state
        # instead of stale history from a previous capture.
        self._state.last_narrated_tokens = None

    @property
    def agent_mode(self) -> bool:
        return self._agent_mode

    # ── Config ───────────────────────────────────────────────────────────────

    def set_proactivity(self, level: int) -> None:
        self._level = max(0, min(4, level))
        logger.info("[proactive] level → %d", self._level)

    @property
    def level(self) -> int:
        return self._level

    def snooze(self, seconds: int) -> None:
        self._snooze_until = time.time() + max(0, seconds)
        logger.info("[proactive] snoozed for %ds", seconds)

    def is_snoozed(self) -> bool:
        return time.time() < self._snooze_until

    def reset_state(self) -> None:
        """Clear accumulated trigger state — useful after a user-initiated
        conversation since the user is clearly not stuck anymore."""
        self._state = TriggerState()
        self._last_fire = time.time()  # reset cooldown too

    def on_trigger(self, cb: TriggerCallback) -> None:
        self._on_trigger = cb

    def attach(self, capture: ScreenCaptureEngine) -> None:
        capture.add_listener(self._on_screen_context)

    # ── Internal: screen listener ────────────────────────────────────────────

    async def _on_screen_context(self, ctx: ScreenContext) -> None:
        cfg = self._active_config()
        if cfg.cooldown_seconds >= 10**8:
            return  # level 0 / 1 → fully disabled (Agent Mode forces lower cooldown)

        now = time.time()

        # First capture seeds state — never fire on cold start.
        is_first_capture = self._state.current_screen_hash is None
        if is_first_capture:
            update_state(self._state, ctx, now)
            self._track_baseline(ctx)
            # Seed Agent Mode's token bag too so the very next capture has a
            # baseline to compare against.
            if cfg.screen_change and ctx.masked_text:
                self._state.last_narrated_tokens = _tokens(ctx.masked_text)
            return

        # Cooldown gate
        if now - self._last_fire < cfg.cooldown_seconds:
            update_state(self._state, ctx, now)
            self._track_baseline(ctx)
            return

        # Snooze gate
        if self.is_snoozed():
            update_state(self._state, ctx, now)
            self._track_baseline(ctx)
            return

        # Run detectors using the PREVIOUS state for context_shift,
        # then update_state with current ctx.
        evt: Optional[TriggerEvent] = None

        # Error loop, context shift, and screen change are the "noticed something
        # new" triggers — they come first. Stuck/idle are "noticed nothing" — last.
        evt = evt or detect_error_loop(self._state, ctx, cfg, now)
        evt = evt or detect_context_shift(self._state, ctx, cfg, now)
        evt = evt or detect_screen_change(self._state, ctx, cfg, now)
        evt = evt or detect_stuck(self._state, ctx, cfg, now)
        evt = evt or detect_idle(self._state, ctx, cfg, now)

        update_state(self._state, ctx, now)
        self._track_baseline(ctx)

        if evt is None:
            return

        # Suppress repeating the exact same trigger kind back-to-back unless
        # cooldown has fully elapsed (twice the level cooldown). Doesn't apply
        # to SCREEN_CHANGE in Agent Mode — that's expected to fire often.
        if (evt.kind != TriggerKind.SCREEN_CHANGE
                and evt.kind == self._state.last_fired_kind
                and now - self._last_fire < cfg.cooldown_seconds * 2):
            return

        self._state.last_fired_kind = evt.kind
        self._last_fire = now

        # Refresh the narrated-token baseline so future diffs compare against
        # the screen we just commented on, not an older one.
        if cfg.screen_change and ctx.masked_text:
            self._state.last_narrated_tokens = _tokens(ctx.masked_text)

        logger.info("[proactive] FIRE %s — %s", evt.kind.value, evt.summary)

        if self._on_trigger:
            try:
                await self._on_trigger(evt)
            except Exception:
                logger.exception("[proactive] callback error")

    def _track_baseline(self, ctx: ScreenContext) -> None:
        """Keep last app/file for the next context-shift comparison."""
        self._state.last_app_bundle = (
            ctx.active_app.bundle_id if ctx.active_app else None
        )
        self._state.last_file_path = ctx.file_path
