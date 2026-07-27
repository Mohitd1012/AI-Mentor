"""
TTS backend providers.

A backend takes text and returns (audio_float32, sample_rate).
The TTSEngine picks a backend at construction time and uses it for synthesis.

Backends:
  • SayBackend     — macOS `say` (fast, robotic, always available)
  • KokoroBackend  — Kokoro 82M ONNX (natural, ~2s/sentence, requires model files)
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Protocol

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


class TTSBackend(Protocol):
    """Synchronous TTS provider. Run synthesise() in an executor."""

    name: str
    default_voice: str

    def synthesise(self, text: str, voice: Optional[str] = None) -> Optional[tuple[np.ndarray, int]]:
        """Returns (float32 audio, sample_rate) or None on failure."""
        ...

    def list_voices(self) -> list[str]:
        """Returns available voice names for this backend."""
        ...


# ── macOS `say` backend ───────────────────────────────────────────────────────

class SayBackend:
    name = "say"
    default_voice = "Samantha"

    def __init__(self, voice: str = "Samantha", rate: int = 175) -> None:
        self.default_voice = voice
        self._rate = rate

    def synthesise(self, text: str, voice: Optional[str] = None) -> Optional[tuple[np.ndarray, int]]:
        text = text.strip()
        if not text:
            return None
        v = voice or self.default_voice
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
                tmp = f.name
            result = subprocess.run(
                ["say", "-v", v, "-r", str(self._rate), "-o", tmp, "--", text],
                capture_output=True, timeout=15,
            )
            if result.returncode != 0:
                logger.warning("[say] failed: %s", result.stderr.decode()[:200])
                return None
            with open(tmp, "rb") as f:
                audio, sr = sf.read(io.BytesIO(f.read()), dtype="float32")
            return audio, int(sr)
        except Exception as exc:
            logger.warning("[say] error: %s", exc)
            return None
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def list_voices(self) -> list[str]:
        try:
            out = subprocess.check_output(["say", "-v", "?"]).decode()
            voices = []
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and "en_" in line:
                    # Take everything before the locale column
                    locale_idx = next((i for i, p in enumerate(parts) if p.startswith("en_")), -1)
                    if locale_idx > 0:
                        voices.append(" ".join(parts[:locale_idx]))
            return voices
        except Exception:
            return [self.default_voice]


# ── Kokoro ONNX backend ───────────────────────────────────────────────────────

class KokoroBackend:
    name = "kokoro"
    default_voice = "af_heart"

    # Mac-friendly default install location: backend/models/kokoro/
    DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "kokoro"

    def __init__(
        self,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang: str = "en-us",
        model_dir: Optional[Path] = None,
    ) -> None:
        from kokoro_onnx import Kokoro

        self.default_voice = voice
        self._speed = speed
        self._lang  = lang

        model_dir = model_dir or self.DEFAULT_MODEL_DIR
        model_path  = model_dir / "kokoro-v1.0.onnx"
        voices_path = model_dir / "voices-v1.0.bin"

        if not model_path.exists() or not voices_path.exists():
            raise FileNotFoundError(
                f"Kokoro model files missing in {model_dir}. "
                f"Download with:\n"
                f"  curl -L -o {model_path} "
                f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx\n"
                f"  curl -L -o {voices_path} "
                f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
            )

        logger.info("[kokoro] loading model from %s …", model_path)
        self._kokoro = Kokoro(str(model_path), str(voices_path))
        logger.info("[kokoro] ready — %d voices available", len(self._kokoro.get_voices()))

    def synthesise(self, text: str, voice: Optional[str] = None) -> Optional[tuple[np.ndarray, int]]:
        text = text.strip()
        if not text:
            return None
        v = voice or self.default_voice
        try:
            audio, sr = self._kokoro.create(text, voice=v, speed=self._speed, lang=self._lang)
            return audio.astype(np.float32), int(sr)
        except Exception as exc:
            logger.warning("[kokoro] synth failed for voice=%s: %s", v, exc)
            return None

    def list_voices(self) -> list[str]:
        try:
            return list(self._kokoro.get_voices())
        except Exception:
            return [self.default_voice]


# ── Factory ──────────────────────────────────────────────────────────────────

def create_backend(provider: str, **kwargs) -> TTSBackend:
    """Construct a backend by name. Falls back to SayBackend on failure."""
    provider = (provider or "say").lower()
    if provider == "kokoro":
        try:
            return KokoroBackend(**kwargs)
        except (FileNotFoundError, ImportError) as exc:
            logger.warning("[tts] Kokoro unavailable (%s) — falling back to macOS say", exc)
            return SayBackend()
    return SayBackend(**kwargs)
