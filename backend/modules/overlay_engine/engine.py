"""
OverlayEngine — server-side tracker of active annotations.

The actual rendering happens in the Tauri overlay window. This engine
gives the backend a place to dispatch annotations (e.g. from the AI router
in future phases) and provides a callback so the WS layer can forward to
the frontend.
"""

import asyncio
import logging
from typing import Callable, Awaitable, Optional

from modules.overlay_engine.models import Annotation

logger = logging.getLogger(__name__)

AnnotateCallback = Callable[[list[Annotation]], Awaitable[None]]
ClearCallback    = Callable[[], Awaitable[None]]


class OverlayEngine:
    def __init__(self) -> None:
        self._on_annotate: Optional[AnnotateCallback] = None
        self._on_clear:    Optional[ClearCallback]    = None
        self._active: dict[str, Annotation] = {}

    # ── Callback wiring ──────────────────────────────────────────────────────

    def on_annotate(self, cb: AnnotateCallback) -> None:
        self._on_annotate = cb

    def on_clear(self, cb: ClearCallback) -> None:
        self._on_clear = cb

    # ── Public API ───────────────────────────────────────────────────────────

    async def annotate(self, items: list[Annotation]) -> None:
        for a in items:
            self._active[a.id] = a
        if self._on_annotate:
            try:
                await self._on_annotate(items)
            except Exception:
                logger.exception("[overlay] annotate callback error")

        # Schedule auto-removal from the active set for any with duration
        for a in items:
            if a.duration_ms and a.duration_ms > 0:
                asyncio.create_task(self._auto_drop(a.id, a.duration_ms))

    async def clear(self) -> None:
        self._active.clear()
        if self._on_clear:
            try:
                await self._on_clear()
            except Exception:
                logger.exception("[overlay] clear callback error")

    def active(self) -> list[Annotation]:
        return list(self._active.values())

    async def _auto_drop(self, ann_id: str, ms: int) -> None:
        await asyncio.sleep(ms / 1000.0)
        self._active.pop(ann_id, None)
