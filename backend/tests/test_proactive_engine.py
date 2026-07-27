"""
Tests for Phase 9 — Proactive Coaching.
"""

import asyncio
import time
import pytest

from modules.proactive_engine import (
    ProactiveMonitor, TriggerEvent, TriggerKind, LEVELS,
)
from modules.proactive_engine.models import AGENT_MODE_CONFIG
from modules.proactive_engine.triggers import (
    TriggerState, _normalize_error, _screen_hash, _tokens,
    detect_stuck, detect_error_loop, detect_context_shift, detect_idle,
    detect_screen_change, update_state,
)
from modules.screen_capture.models import (
    ScreenContext, ContentType, ActiveApp,
)


def _ctx(app_name="Code", bundle="com.microsoft.VSCode", file_path=None,
         errors=None, text="hello world") -> ScreenContext:
    return ScreenContext(
        active_app=ActiveApp(name=app_name, bundle_id=bundle, pid=1),
        raw_text=text,
        masked_text=text,
        content_type=ContentType.CODE,
        file_path=file_path,
        error_messages=errors or [],
        is_blank=False,
        capture_width=1920, capture_height=1080,
    )


# ── Normalisation helpers ─────────────────────────────────────────────────────

class TestNormalisation:
    def test_normalize_strips_numbers(self):
        a = _normalize_error("TypeError at line 42 in main.py:17")
        b = _normalize_error("TypeError at line 99 in main.py:3")
        assert a == b

    def test_normalize_strips_quotes(self):
        a = _normalize_error("KeyError: 'foo'")
        b = _normalize_error("KeyError: 'bar'")
        assert a == b

    def test_normalize_lowercases(self):
        assert _normalize_error("FATAL ERROR") == _normalize_error("fatal error")

    def test_screen_hash_changes_on_text_change(self):
        a = _screen_hash(_ctx(text="foo"))
        b = _screen_hash(_ctx(text="bar"))
        assert a != b

    def test_screen_hash_stable_on_identical_text(self):
        a = _screen_hash(_ctx(text="same content"))
        b = _screen_hash(_ctx(text="same content"))
        assert a == b


# ── Individual detectors ──────────────────────────────────────────────────────

class TestDetectStuck:
    def test_fires_after_threshold(self):
        cfg = LEVELS[3]  # stuck=300s
        st  = TriggerState()
        now = 1000.0
        update_state(st, _ctx(), now)
        evt = detect_stuck(st, _ctx(), cfg, now + 400)
        assert evt is not None and evt.kind == TriggerKind.STUCK

    def test_does_not_fire_before_threshold(self):
        cfg = LEVELS[3]
        st  = TriggerState()
        now = 1000.0
        update_state(st, _ctx(), now)
        evt = detect_stuck(st, _ctx(), cfg, now + 60)
        assert evt is None

    def test_disabled_at_low_level(self):
        cfg = LEVELS[1]
        st  = TriggerState()
        evt = detect_stuck(st, _ctx(), cfg, time.time())
        assert evt is None

    def test_skips_blank_frames(self):
        cfg = LEVELS[4]
        st  = TriggerState()
        st.screen_hash_started_at = 0
        ctx = _ctx()
        ctx.is_blank = True
        evt = detect_stuck(st, ctx, cfg, 10**9)
        assert evt is None


class TestDetectErrorLoop:
    def test_fires_on_repeated_errors(self):
        cfg = LEVELS[2]  # min 3
        st  = TriggerState(error_history=[
            "typeerror at line N", "typeerror at line N", "typeerror at line N",
        ])
        evt = detect_error_loop(st, _ctx(), cfg, time.time())
        assert evt is not None and evt.kind == TriggerKind.ERROR_LOOP
        assert evt.details["count"] == 3

    def test_does_not_fire_with_varied_errors(self):
        cfg = LEVELS[2]
        st  = TriggerState(error_history=["e1", "e2", "e3"])
        evt = detect_error_loop(st, _ctx(), cfg, time.time())
        assert evt is None


class TestDetectContextShift:
    def test_fires_on_app_change(self):
        cfg = LEVELS[3]
        st  = TriggerState(last_app_bundle="com.apple.Terminal")
        evt = detect_context_shift(st, _ctx(bundle="com.microsoft.VSCode"),
                                    cfg, time.time())
        assert evt is not None and evt.kind == TriggerKind.CONTEXT_SHIFT

    def test_fires_on_file_change(self):
        cfg = LEVELS[3]
        st  = TriggerState(last_app_bundle="com.microsoft.VSCode",
                            last_file_path="/foo.py")
        evt = detect_context_shift(st, _ctx(file_path="/bar.py"),
                                    cfg, time.time())
        assert evt is not None

    def test_no_baseline_no_fire(self):
        cfg = LEVELS[3]
        st  = TriggerState()   # last_app_bundle = None
        evt = detect_context_shift(st, _ctx(), cfg, time.time())
        assert evt is None

    def test_disabled_at_low_level(self):
        cfg = LEVELS[2]  # context_shift=False
        st  = TriggerState(last_app_bundle="x")
        evt = detect_context_shift(st, _ctx(), cfg, time.time())
        assert evt is None


class TestDetectIdle:
    def test_fires_after_long_inactivity(self):
        cfg = LEVELS[4]  # idle=900
        st  = TriggerState(screen_hash_started_at=0)
        evt = detect_idle(st, _ctx(), cfg, 2000)
        assert evt is not None and evt.kind == TriggerKind.IDLE

    def test_disabled_at_low_level(self):
        cfg = LEVELS[2]  # idle=None
        st  = TriggerState(screen_hash_started_at=0)
        evt = detect_idle(st, _ctx(), cfg, 10**6)
        assert evt is None


# ── ProactiveMonitor end-to-end ───────────────────────────────────────────────

class TestProactiveMonitor:
    @pytest.mark.asyncio
    async def test_low_level_does_not_fire(self):
        mon = ProactiveMonitor(proactivity=1)
        fires = []
        mon.on_trigger(lambda e: fires.append(e))
        # Manually push a context that would otherwise fire
        await mon._on_screen_context(_ctx(text="lots of stuck content"))
        await asyncio.sleep(0.05)
        assert fires == []

    @pytest.mark.asyncio
    async def test_snooze_silences(self):
        mon = ProactiveMonitor(proactivity=4)
        mon._state.error_history = ["e", "e", "e"]
        mon.snooze(60)
        fires = []
        async def cb(e):
            fires.append(e)
        mon.on_trigger(cb)
        await mon._on_screen_context(_ctx(errors=["e", "e", "e"]))
        await asyncio.sleep(0.05)
        assert fires == []

    @pytest.mark.asyncio
    async def test_cooldown_blocks_second_fire(self):
        mon = ProactiveMonitor(proactivity=4)

        fires = []
        async def cb(e):
            fires.append(e)
        mon.on_trigger(cb)

        # Seed state — never fires on first capture
        await mon._on_screen_context(_ctx(errors=["e at line N"] * 3))
        await asyncio.sleep(0.05)

        # Now state is seeded with errors; this call fires
        await mon._on_screen_context(_ctx(errors=["e at line N"] * 3))
        await asyncio.sleep(0.05)
        first_count = len(fires)
        assert first_count >= 1

        # Immediate third call → cooldown blocks
        await mon._on_screen_context(_ctx(errors=["e at line N"] * 3))
        await asyncio.sleep(0.05)
        assert len(fires) == first_count

    def test_reset_state_clears(self):
        mon = ProactiveMonitor(proactivity=4)
        mon._state.error_history = ["x"] * 5
        mon._state.last_fired_kind = TriggerKind.STUCK
        mon.reset_state()
        assert mon._state.error_history == []
        assert mon._state.last_fired_kind is None

    def test_set_proactivity_clamps(self):
        mon = ProactiveMonitor()
        mon.set_proactivity(99)
        assert mon.level == 4
        mon.set_proactivity(-5)
        assert mon.level == 0

    @pytest.mark.asyncio
    async def test_fires_at_high_level_with_repeated_errors(self):
        mon = ProactiveMonitor(proactivity=4)
        fires: list[TriggerEvent] = []
        async def cb(e):
            fires.append(e)
        mon.on_trigger(cb)

        # First call seeds state, second already meets count for level 4 (min=2)
        await mon._on_screen_context(_ctx(errors=["typeerror at line N"] * 2))
        await mon._on_screen_context(_ctx(errors=["typeerror at line N"]))
        await asyncio.sleep(0.05)

        assert len(fires) >= 1
        assert fires[0].kind == TriggerKind.ERROR_LOOP


# ── Screen change / Agent Mode ────────────────────────────────────────────────

class TestScreenChangeDetector:
    def test_no_fire_when_disabled(self):
        cfg = LEVELS[4]   # screen_change=False by default
        st  = TriggerState(last_narrated_tokens={"foo"})
        evt = detect_screen_change(
            st, _ctx(text="completely different content"), cfg, time.time())
        assert evt is None

    def test_no_fire_on_first_capture(self):
        # last_narrated_tokens is None → seed only, no fire
        cfg = AGENT_MODE_CONFIG
        st  = TriggerState()
        evt = detect_screen_change(st, _ctx(text="hello world"), cfg, time.time())
        assert evt is None

    def test_fires_on_substantial_delta(self):
        cfg = AGENT_MODE_CONFIG   # min_diff=0.35
        st  = TriggerState(last_narrated_tokens={"old", "stuff", "previous"})
        # Almost no overlap with previous tokens
        ctx = _ctx(text="brand new content about python async kubernetes deploy")
        evt = detect_screen_change(st, ctx, cfg, time.time())
        assert evt is not None
        assert evt.kind == TriggerKind.SCREEN_CHANGE
        assert evt.details["delta_pct"] >= 0.35

    def test_no_fire_on_small_delta(self):
        cfg = AGENT_MODE_CONFIG
        prev = _tokens("python typescript kubernetes deploy run start")
        st  = TriggerState(last_narrated_tokens=prev)
        # Same text plus one new word → tiny delta
        ctx = _ctx(text="python typescript kubernetes deploy run start newword")
        evt = detect_screen_change(st, ctx, cfg, time.time())
        assert evt is None

    def test_skips_blank_frame(self):
        cfg = AGENT_MODE_CONFIG
        st  = TriggerState(last_narrated_tokens={"x"})
        ctx = _ctx(text="lots of new tokens here xxx yyy zzz")
        ctx.is_blank = True
        evt = detect_screen_change(st, ctx, cfg, time.time())
        assert evt is None

    def test_skips_short_text(self):
        cfg = AGENT_MODE_CONFIG
        st  = TriggerState(last_narrated_tokens={"x"})
        ctx = _ctx(text="hi")
        evt = detect_screen_change(st, ctx, cfg, time.time())
        assert evt is None


class TestAgentMode:
    def test_default_off(self):
        mon = ProactiveMonitor(proactivity=0)
        assert mon.agent_mode is False

    def test_set_agent_mode_resets_token_baseline(self):
        mon = ProactiveMonitor(proactivity=2)
        mon._state.last_narrated_tokens = {"old"}
        mon.set_agent_mode(True)
        assert mon.agent_mode is True
        assert mon._state.last_narrated_tokens is None

    def test_agent_mode_overrides_low_proactivity(self):
        """Even at proactivity=0 (which is fully disabled), Agent Mode runs."""
        mon = ProactiveMonitor(proactivity=0)
        # In agent mode, cooldown should NOT be the level-0 infinite cooldown
        mon.set_agent_mode(True)
        cfg = mon._active_config()
        assert cfg.cooldown_seconds < 10**8
        assert cfg.screen_change is True

    @pytest.mark.asyncio
    async def test_agent_mode_fires_screen_change(self):
        mon = ProactiveMonitor(proactivity=0)
        mon.set_agent_mode(True)

        fires: list[TriggerEvent] = []
        async def cb(e):
            fires.append(e)
        mon.on_trigger(cb)

        # First capture seeds tokens
        await mon._on_screen_context(
            _ctx(text="docker compose up nginx postgres redis init")
        )
        await asyncio.sleep(0.05)

        # Big content change — should fire
        await mon._on_screen_context(
            _ctx(text="python pytest unittest mock fixture asyncio coroutine yield")
        )
        await asyncio.sleep(0.05)

        assert any(e.kind == TriggerKind.SCREEN_CHANGE for e in fires)
