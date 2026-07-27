"""
Pure trigger detectors — given the current screen context + history,
return a TriggerEvent or None.

These are intentionally side-effect-free so they're easy to test.
"""

import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from modules.proactive_engine.models import LevelConfig, TriggerEvent, TriggerKind
from modules.screen_capture import ScreenContext


# ── Per-monitor mutable state ─────────────────────────────────────────────────

@dataclass
class TriggerState:
    """Running state the monitor accumulates between captures."""
    current_screen_hash: Optional[str]  = None
    screen_hash_started_at: float       = 0.0
    last_app_bundle:    Optional[str]   = None
    last_file_path:     Optional[str]   = None
    last_capture_at:    float           = 0.0
    error_history:      list[str]       = field(default_factory=list)
    last_fired_kind:    Optional[TriggerKind] = None
    # Agent Mode: token bag from the last narrated screen.
    last_narrated_tokens: Optional[set[str]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _screen_hash(ctx: ScreenContext) -> str:
    """Stable hash of the meaningful part of a screen — used to detect 'stuck'."""
    # Hash app + first 400 chars of masked text. Avoids noise from cursor blink,
    # clock ticks, etc. that change unrelated pixels.
    h = hashlib.md5()
    h.update((ctx.active_app.bundle_id if ctx.active_app else "").encode())
    h.update(b"|")
    h.update(ctx.masked_text[:400].encode("utf-8", errors="ignore"))
    return h.hexdigest()


def _normalize_error(line: str) -> str:
    """Strip variable bits (paths, line numbers, timestamps) so identical
    errors at different locations still match."""
    s = line.strip().lower()
    s = re.sub(r"\d+", "N", s)
    s = re.sub(r"['\"`]([^'\"`]*)['\"`]", "X", s)
    s = re.sub(r"\s+", " ", s)
    return s[:200]


# ── Detectors ─────────────────────────────────────────────────────────────────

def update_state(state: TriggerState, ctx: ScreenContext, now: float) -> None:
    """Update mutable state based on the latest screen capture."""
    h = _screen_hash(ctx)
    if h != state.current_screen_hash:
        state.current_screen_hash    = h
        state.screen_hash_started_at = now

    state.last_capture_at = now

    if ctx.error_messages:
        state.error_history.extend(_normalize_error(e) for e in ctx.error_messages)
        if len(state.error_history) > 50:
            state.error_history = state.error_history[-50:]


def detect_stuck(state: TriggerState, ctx: ScreenContext, cfg: LevelConfig,
                 now: float) -> Optional[TriggerEvent]:
    if cfg.stuck_seconds is None or ctx.is_blank:
        return None
    elapsed = now - state.screen_hash_started_at
    if elapsed < cfg.stuck_seconds:
        return None
    minutes = int(elapsed / 60)
    app = ctx.active_app.name if ctx.active_app else "an app"
    return TriggerEvent(
        kind=TriggerKind.STUCK,
        summary=f"User has been on the same screen in {app} for ~{minutes} min.",
        details={"app": app, "minutes": minutes, "content_type": ctx.content_type.value},
    )


def detect_error_loop(state: TriggerState, ctx: ScreenContext, cfg: LevelConfig,
                      now: float) -> Optional[TriggerEvent]:
    if cfg.error_loop_min_count is None or not state.error_history:
        return None
    counts = Counter(state.error_history)
    top, count = counts.most_common(1)[0]
    if count < cfg.error_loop_min_count:
        return None
    return TriggerEvent(
        kind=TriggerKind.ERROR_LOOP,
        summary=f"The same error has appeared {count} times on screen: '{top[:140]}'",
        details={"normalized_error": top, "count": count},
    )


def detect_context_shift(prev_state: TriggerState, ctx: ScreenContext,
                         cfg: LevelConfig, now: float) -> Optional[TriggerEvent]:
    if not cfg.context_shift or ctx.is_blank:
        return None
    bundle = ctx.active_app.bundle_id if ctx.active_app else None
    file_path = ctx.file_path
    if bundle == prev_state.last_app_bundle and file_path == prev_state.last_file_path:
        return None
    if prev_state.last_app_bundle is None:
        # first capture — establishes baseline, not a shift
        return None
    app = ctx.active_app.name if ctx.active_app else "another app"
    return TriggerEvent(
        kind=TriggerKind.CONTEXT_SHIFT,
        summary=(f"User switched to {app}"
                 + (f" and opened {file_path}" if file_path else "")
                 + "."),
        details={"app": app, "file": file_path},
    )


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _tokens(text: str) -> set[str]:
    """Lowercase content tokens, length>=3 — what the page is 'about'."""
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def detect_screen_change(state: TriggerState, ctx: ScreenContext,
                          cfg: LevelConfig, now: float) -> Optional[TriggerEvent]:
    """
    Agent Mode trigger: fires when the screen content shifted meaningfully
    since the last narrated frame. Uses Jaccard distance on content tokens
    so cursor blinks / clocks / scrollbars don't register.
    """
    if not cfg.screen_change or ctx.is_blank:
        return None
    if not ctx.masked_text or len(ctx.masked_text) < 40:
        return None

    current = _tokens(ctx.masked_text)
    prev    = state.last_narrated_tokens

    if not current:
        return None
    if prev is None:
        # First Agent-Mode capture — seed, don't fire.
        return None

    new_tokens = current - prev
    if not current:
        return None
    delta = len(new_tokens) / max(1, len(current))

    if delta < cfg.screen_change_min_diff:
        return None

    app = ctx.active_app.name if ctx.active_app else "an app"
    return TriggerEvent(
        kind=TriggerKind.SCREEN_CHANGE,
        summary=(
            f"Screen in {app} changed meaningfully "
            f"({int(delta*100)}% new content)."
        ),
        details={
            "app": app,
            "content_type": ctx.content_type.value,
            "file": ctx.file_path,
            "delta_pct": round(delta, 3),
            "sample_new_tokens": list(new_tokens)[:8],
        },
    )


def detect_idle(state: TriggerState, ctx: ScreenContext, cfg: LevelConfig,
                now: float) -> Optional[TriggerEvent]:
    """Idle = same screen for a very long time AND no errors and no recent input."""
    if cfg.idle_seconds is None:
        return None
    elapsed = now - state.screen_hash_started_at
    if elapsed < cfg.idle_seconds:
        return None
    return TriggerEvent(
        kind=TriggerKind.IDLE,
        summary=f"User appears idle (~{int(elapsed/60)} min without screen change).",
        details={"minutes": int(elapsed/60)},
    )


# Convenience: run every detector in priority order, return the first hit.
DETECT_ORDER = (detect_error_loop, detect_stuck, detect_context_shift, detect_idle)


def detect_any(state: TriggerState, ctx: ScreenContext, cfg: LevelConfig,
               now: Optional[float] = None) -> Optional[TriggerEvent]:
    now = now or time.time()
    # detect_context_shift compares against PREVIOUS state, so check it before
    # we update_state with current ctx — caller is responsible for that order.
    for fn in DETECT_ORDER:
        evt = fn(state, ctx, cfg, now)
        if evt is not None:
            return evt
    return None
