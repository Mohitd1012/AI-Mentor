"""
Tests for Phase 8 — Visual Overlay Engine.
"""

import asyncio
import pytest

from modules.overlay_engine import (
    OverlayEngine, HighlightAnnotation, CircleAnnotation,
    ArrowAnnotation, LabelAnnotation,
)


# ── Annotation models ────────────────────────────────────────────────────────

class TestAnnotationModels:
    def test_highlight_defaults(self):
        a = HighlightAnnotation(x=10, y=20, w=100, h=50)
        assert a.kind == "highlight"
        assert a.color == "accent"
        assert a.duration_ms == 5000
        assert a.id  # auto-generated

    def test_arrow_required_fields(self):
        a = ArrowAnnotation(x1=0, y1=0, x2=100, y2=100, color="warning")
        assert a.kind == "arrow"
        assert a.color == "warning"

    def test_label_text(self):
        a = LabelAnnotation(x=50, y=50, text="hi")
        assert a.text == "hi"
        assert a.kind == "label"

    def test_invalid_color_rejected(self):
        with pytest.raises(Exception):
            HighlightAnnotation(x=0, y=0, w=10, h=10, color="rainbow")

    def test_serialises_to_dict(self):
        a = CircleAnnotation(x=100, y=100, r=20, label="here")
        d = a.model_dump()
        assert d["kind"] == "circle"
        assert d["x"] == 100
        assert d["label"] == "here"


# ── Engine behaviour ──────────────────────────────────────────────────────────

class TestOverlayEngine:
    @pytest.mark.asyncio
    async def test_annotate_calls_callback(self):
        engine = OverlayEngine()
        captured = []

        async def cb(items):
            captured.extend(items)

        engine.on_annotate(cb)
        await engine.annotate([HighlightAnnotation(x=0, y=0, w=10, h=10)])
        assert len(captured) == 1

    @pytest.mark.asyncio
    async def test_clear_calls_callback(self):
        engine = OverlayEngine()
        cleared = []

        async def cb():
            cleared.append(True)

        engine.on_clear(cb)
        await engine.clear()
        assert cleared == [True]

    @pytest.mark.asyncio
    async def test_active_tracks_annotations(self):
        engine = OverlayEngine()
        h = HighlightAnnotation(x=0, y=0, w=10, h=10, duration_ms=0)
        await engine.annotate([h])
        assert len(engine.active()) == 1
        await engine.clear()
        assert engine.active() == []

    @pytest.mark.asyncio
    async def test_auto_drop_after_duration(self):
        engine = OverlayEngine()
        h = HighlightAnnotation(x=0, y=0, w=10, h=10, duration_ms=50)
        await engine.annotate([h])
        assert len(engine.active()) == 1
        await asyncio.sleep(0.12)
        assert engine.active() == []

    @pytest.mark.asyncio
    async def test_callbacks_isolated_from_exceptions(self):
        engine = OverlayEngine()

        async def bad_cb(items):
            raise RuntimeError("boom")

        engine.on_annotate(bad_cb)
        # Should not raise even though callback errors
        await engine.annotate([CircleAnnotation(x=0, y=0, r=5)])
        # Annotation still recorded
        assert len(engine.active()) == 1

    @pytest.mark.asyncio
    async def test_batch_annotate(self):
        engine = OverlayEngine()
        items = [
            HighlightAnnotation(x=0, y=0, w=10, h=10),
            CircleAnnotation(x=50, y=50, r=20),
            ArrowAnnotation(x1=0, y1=0, x2=100, y2=100),
            LabelAnnotation(x=200, y=200, text="hello"),
        ]
        await engine.annotate(items)
        assert len(engine.active()) == 4
