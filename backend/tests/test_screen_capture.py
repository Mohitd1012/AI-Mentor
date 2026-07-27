"""
Tests for Phase 2 — Screen Capture Engine.

Unit tests use synthetic data and mocks; no live screen required.
Integration tests tagged @pytest.mark.integration.
"""

import numpy as np
import pytest
from PIL import Image, ImageDraw
from unittest.mock import patch, MagicMock

from modules.screen_capture.masker import mask, scan_for_secrets
from modules.screen_capture.frame_differ import FrameDiffer
from modules.screen_capture.ocr_engine import is_blank_frame, observations_to_text
from modules.screen_capture.models import (
    ScreenContext, ContentType, TextObservation, BoundingBox, ActiveApp,
)
from modules.screen_capture.context_extractor import extract
from modules.screen_capture.app_tracker import is_excluded


# ── Masker ────────────────────────────────────────────────────────────────────

class TestMasker:
    def test_openai_key_masked(self):
        text = "export OPENAI_KEY=sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd"
        result = mask(text)
        assert "sk-" not in result
        assert "[OPENAI_KEY]" in result

    def test_password_kv_masked(self):
        result = mask("password=supersecret123")
        assert "supersecret123" not in result
        assert "[REDACTED]" in result

    def test_github_token_masked(self):
        result = mask("token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZabcdefghij")
        assert "ghp_" not in result

    def test_hex_secret_masked(self):
        result = mask("key: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4")
        assert "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4" not in result

    def test_normal_text_unchanged(self):
        text = "def hello(): return 'world'"
        assert mask(text) == text

    def test_scan_detects_types(self):
        text = "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd"
        found = scan_for_secrets(text)
        assert "openai_key" in found

    def test_scan_clean_text(self):
        assert scan_for_secrets("hello world") == []


# ── Frame Differ ──────────────────────────────────────────────────────────────

class TestFrameDiffer:
    def _frame(self, value: int) -> np.ndarray:
        return np.full((100, 100, 3), value, dtype=np.uint8)

    def test_first_frame_always_changed(self):
        d = FrameDiffer()
        assert d.has_changed(self._frame(128)) is True

    def test_identical_frame_unchanged(self):
        d = FrameDiffer()
        f = self._frame(128)
        d.has_changed(f)           # first call
        assert d.has_changed(f) is False

    def test_different_frame_detected(self):
        d = FrameDiffer(threshold=5)
        d.has_changed(self._frame(0))
        assert d.has_changed(self._frame(255)) is True

    def test_reset_triggers_change(self):
        d = FrameDiffer()
        f = self._frame(100)
        d.has_changed(f)
        d.has_changed(f)           # now unchanged
        d.reset()
        assert d.has_changed(f) is True


# ── Blank frame detection ─────────────────────────────────────────────────────

class TestBlankFrame:
    def test_white_frame_is_blank(self):
        frame = np.full((100, 100, 3), 255, dtype=np.uint8)
        assert is_blank_frame(frame) is True

    def test_dark_frame_not_blank(self):
        frame = np.full((100, 100, 3), 30, dtype=np.uint8)
        assert is_blank_frame(frame) is False

    def test_mixed_frame_not_blank(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame[:50] = 255
        assert is_blank_frame(frame) is False


# ── OCR text reconstruction ───────────────────────────────────────────────────

class TestObservationsToText:
    def _obs(self, text, y, x=0.0):
        return TextObservation(text=text, confidence=0.99,
                               bbox=BoundingBox(x=x, y=y, width=0.5, height=0.05))

    def test_single_line(self):
        obs = [self._obs("hello world", 0.1)]
        assert observations_to_text(obs) == "hello world"

    def test_multi_line_sorted(self):
        obs = [self._obs("line2", 0.5), self._obs("line1", 0.1)]
        result = observations_to_text(obs)
        assert result.index("line1") < result.index("line2")

    def test_empty_returns_empty(self):
        assert observations_to_text([]) == ""


# ── Context Extractor ─────────────────────────────────────────────────────────

class TestContextExtractor:
    def _app(self, name, bundle_id):
        return ActiveApp(name=name, bundle_id=bundle_id, pid=1234)

    def test_ide_classified_as_code(self):
        app = self._app("Code", "com.microsoft.VSCode")
        ctx = extract([], "def foo(): pass", app, 1920, 1080, False)
        assert ctx.content_type == ContentType.CODE

    def test_terminal_classified(self):
        app = self._app("Terminal", "com.apple.Terminal")
        ctx = extract([], "$ pip install numpy", app, 1920, 1080, False)
        assert ctx.content_type == ContentType.TERMINAL

    def test_url_extracted(self):
        ctx = extract([], "Visit https://github.com/user/repo", None, 1920, 1080, False)
        assert "https://github.com/user/repo" in ctx.urls

    def test_error_extracted(self):
        ctx = extract([], "Error: connection refused on port 5432", None, 1920, 1080, False)
        assert any("connection refused" in e for e in ctx.error_messages)

    def test_secrets_masked_in_context(self):
        ctx = extract([], "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890ab",
                      None, 1920, 1080, False)
        assert "sk-" not in ctx.masked_text

    def test_blank_flag_passed_through(self):
        ctx = extract([], "", None, 1920, 1080, True)
        assert ctx.is_blank is True

    def test_prompt_block_empty_when_blank(self):
        ctx = extract([], "", None, 1920, 1080, True)
        assert ctx.to_prompt_block() == ""

    def test_prompt_block_contains_app_name(self):
        app = self._app("VSCode", "com.microsoft.VSCode")
        ctx = extract([], "def foo(): pass", app, 1920, 1080, False)
        block = ctx.to_prompt_block()
        assert "VSCode" in block

    def test_prompt_block_truncates_long_text(self):
        long_text = "x " * 1000
        ctx = extract([], long_text, None, 1920, 1080, False)
        block = ctx.to_prompt_block()
        assert len(block) < 3000


# ── App Tracker ───────────────────────────────────────────────────────────────

class TestAppTracker:
    def test_excluded_bundle_detected(self):
        app = ActiveApp("Keychain", "com.apple.keychainaccess", 100)
        assert is_excluded(app, set()) is True

    def test_custom_excluded_bundle(self):
        app = ActiveApp("MyApp", "com.example.myapp", 200)
        assert is_excluded(app, {"com.example.myapp"}) is True

    def test_normal_app_not_excluded(self):
        app = ActiveApp("VSCode", "com.microsoft.VSCode", 300)
        assert is_excluded(app, set()) is False

    def test_none_app_not_excluded(self):
        assert is_excluded(None, set()) is False


# ── Integration: live OCR ─────────────────────────────────────────────────────

@pytest.mark.integration
class TestOCRIntegration:
    def test_ocr_reads_known_text(self):
        from modules.screen_capture.ocr_engine import ocr_image, observations_to_text

        img = Image.new("RGB", (600, 100), "white")
        ImageDraw.Draw(img).text((10, 30), "Hello from Vision OCR", fill="black")

        obs = ocr_image(img)
        text = observations_to_text(obs)
        assert "Hello" in text
        assert "Vision" in text

    def test_ocr_detects_code_text(self):
        from modules.screen_capture.ocr_engine import ocr_image, observations_to_text

        img = Image.new("RGB", (700, 120), "white")
        draw = ImageDraw.Draw(img)
        draw.text((10, 20), "def fibonacci(n):", fill="black")
        draw.text((10, 60), "    return n if n < 2 else fibonacci(n-1) + fibonacci(n-2)", fill="black")

        obs = ocr_image(img)
        text = observations_to_text(obs)
        assert "fibonacci" in text.lower()
