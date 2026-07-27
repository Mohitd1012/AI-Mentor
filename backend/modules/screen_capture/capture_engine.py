"""
Screen Capture Engine — main loop.

Runs as an asyncio background task. Every `interval_seconds`:
  1. Grab screen frame (mss, in executor — blocking)
  2. Check excluded apps (AppKit)
  3. Diff against previous frame; skip if unchanged
  4. Run Apple Vision OCR (in executor — blocking)
  5. Extract structured context
  6. Notify registered listeners

Privacy controls:
  - paused flag: stops all capture
  - excluded_bundles: skip specific apps
"""

import asyncio
import logging
import numpy as np
from PIL import Image
from typing import Callable, Awaitable, Optional

from modules.screen_capture import app_tracker, ocr_engine, context_extractor
from modules.screen_capture.frame_differ import FrameDiffer
from modules.screen_capture.ocr_engine import observations_to_text
from modules.screen_capture.models import ScreenContext

logger = logging.getLogger(__name__)

ContextListener = Callable[[ScreenContext], Awaitable[None]]

# Warn once about Screen Recording permission
_permission_warned = False


class ScreenCaptureEngine:
    def __init__(
        self,
        interval_seconds: float = 2.0,
        monitor_index: int = 1,          # 1 = primary display
    ) -> None:
        self._interval = interval_seconds
        self._monitor_index = monitor_index
        self._differ = FrameDiffer(threshold=10)
        self._paused = False
        self._excluded_bundles: set[str] = set()
        self._listeners: list[ContextListener] = []
        self._task: Optional[asyncio.Task] = None
        self._last_context: Optional[ScreenContext] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_listener(self, cb: ContextListener) -> None:
        self._listeners.append(cb)

    def pause(self) -> None:
        self._paused = True
        logger.info("[capture] paused")

    def resume(self) -> None:
        self._paused = False
        logger.info("[capture] resumed")

    def set_excluded_bundles(self, bundles: set[str]) -> None:
        self._excluded_bundles = bundles

    def add_excluded_bundle(self, bundle_id: str) -> None:
        self._excluded_bundles.add(bundle_id)

    @property
    def last_context(self) -> Optional[ScreenContext]:
        return self._last_context

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="screen_capture")
        logger.info("[capture] started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[capture] stopped")

    # ── Internal loop ──────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        global _permission_warned
        loop = asyncio.get_running_loop()

        while True:
            try:
                await asyncio.sleep(self._interval)

                if self._paused:
                    continue

                # ① Check active app (synchronous but fast)
                active_app = await loop.run_in_executor(
                    None, app_tracker.get_active_app
                )
                if app_tracker.is_excluded(active_app, self._excluded_bundles):
                    logger.debug("[capture] app excluded: %s", active_app)
                    continue

                # ② Capture frame
                frame_rgb = await loop.run_in_executor(None, self._grab_frame)
                if frame_rgb is None:
                    continue

                # ③ Blank frame = Screen Recording permission denied
                if ocr_engine.is_blank_frame(frame_rgb):
                    if not _permission_warned:
                        logger.warning(
                            "[capture] Screen appears blank — grant Screen Recording "
                            "permission to this app in System Settings > Privacy."
                        )
                        _permission_warned = True
                    ctx = context_extractor.extract(
                        observations=[], raw_text="",
                        active_app=active_app,
                        capture_w=frame_rgb.shape[1],
                        capture_h=frame_rgb.shape[0],
                        is_blank=True,
                    )
                    self._last_context = ctx
                    await self._notify(ctx)
                    continue

                # ④ Frame diff — skip unchanged screens
                if not self._differ.has_changed(frame_rgb):
                    logger.debug("[capture] frame unchanged, skipping OCR")
                    continue

                # ⑤ OCR
                pil_image = Image.fromarray(frame_rgb)
                observations = await loop.run_in_executor(
                    None, ocr_engine.ocr_image, pil_image
                )
                raw_text = observations_to_text(observations)

                # ⑥ Build context
                ctx = context_extractor.extract(
                    observations=observations,
                    raw_text=raw_text,
                    active_app=active_app,
                    capture_w=frame_rgb.shape[1],
                    capture_h=frame_rgb.shape[0],
                    is_blank=False,
                )
                self._last_context = ctx
                logger.debug(
                    "[capture] context updated app=%s type=%s chars=%d",
                    active_app.name if active_app else "?",
                    ctx.content_type.value,
                    len(raw_text),
                )

                # ⑦ Notify listeners
                await self._notify(ctx)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[capture] unexpected error in capture loop")

    def _grab_frame(self) -> Optional[np.ndarray]:
        """Synchronous frame grab — run in executor."""
        try:
            import mss
            with mss.MSS() as sct:
                monitors = sct.monitors
                if self._monitor_index >= len(monitors):
                    logger.warning(
                        "[capture] monitor %d not found, using primary",
                        self._monitor_index,
                    )
                    monitor = monitors[1]
                else:
                    monitor = monitors[self._monitor_index]
                shot = sct.grab(monitor)
                # BGRA → RGB
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                return np.array(img)
        except Exception as exc:
            logger.warning("[capture] grab failed: %s", exc)
            return None

    async def _notify(self, ctx: ScreenContext) -> None:
        for listener in self._listeners:
            try:
                await listener(ctx)
            except Exception:
                logger.exception("[capture] listener error")
