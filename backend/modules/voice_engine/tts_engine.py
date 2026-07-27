"""
TTS engine — backend-agnostic synthesis + smooth interruptible playback.

The engine delegates synthesis to a swappable backend (macOS `say`, Kokoro, …)
and handles playback uniformly via sounddevice.
"""

import logging
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from modules.voice_engine.tts_backends import TTSBackend, create_backend

logger = logging.getLogger(__name__)

_CANCEL_POLL_S = 0.02   # 20ms cancellation polling


class _PlaybackToken:
    def __init__(self) -> None:
        self.cancelled = False
    def cancel(self) -> None:
        self.cancelled = True


class TTSEngine:
    """
    Backend-agnostic TTS with smooth interruptible playback.

    Construct with provider name + provider-specific kwargs:
        TTSEngine(provider="kokoro", voice="af_heart")
        TTSEngine(provider="say",    voice="Samantha", rate=175)
    """

    def __init__(self, provider: str = "kokoro", **backend_kwargs) -> None:
        self._lock = threading.Lock()
        self._current_token: Optional[_PlaybackToken] = None
        self._backend: TTSBackend = create_backend(provider, **backend_kwargs)
        logger.info("[tts] backend=%s default_voice=%s",
                    self._backend.name, self._backend.default_voice)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def voice(self) -> str:
        return self._backend.default_voice

    def list_voices(self) -> list[str]:
        return self._backend.list_voices()

    def set_voice(self, voice: str) -> None:
        self._backend.default_voice = voice
        logger.info("[tts] voice → %s (%s)", voice, self._backend.name)

    def set_backend(self, provider: str, **kwargs) -> None:
        """Swap to a different TTS provider at runtime."""
        self.interrupt()
        self._backend = create_backend(provider, **kwargs)
        logger.info("[tts] backend switched to %s", self._backend.name)

    # ── Interrupt ─────────────────────────────────────────────────────────────

    def interrupt(self) -> None:
        with self._lock:
            if self._current_token:
                self._current_token.cancel()
        try:
            sd.stop()
        except Exception:
            pass

    # ── Synthesise + play ─────────────────────────────────────────────────────

    def synthesise(self, text: str, voice: Optional[str] = None) -> Optional[tuple[np.ndarray, int]]:
        return self._backend.synthesise(text, voice=voice)

    def play(self, audio: np.ndarray, sample_rate: int = 22050) -> bool:
        if audio is None or len(audio) == 0:
            return False

        token = _PlaybackToken()
        with self._lock:
            if self._current_token:
                self._current_token.cancel()
            self._current_token = token

        try:
            sd.play(audio, samplerate=sample_rate, blocking=False)
            duration_s = len(audio) / sample_rate
            deadline = time.monotonic() + duration_s + 0.5

            while time.monotonic() < deadline:
                if token.cancelled:
                    sd.stop()
                    return False
                try:
                    stream = sd.get_stream()
                    if not stream.active:
                        return True
                except Exception:
                    return True
                time.sleep(_CANCEL_POLL_S)

            sd.wait()
            return not token.cancelled

        except Exception as exc:
            logger.warning("[tts] play error: %s", exc)
            return False
        finally:
            with self._lock:
                if self._current_token is token:
                    self._current_token = None

    def synthesise_and_play(self, text: str, voice: Optional[str] = None) -> bool:
        result = self.synthesise(text, voice=voice)
        if result is None:
            return False
        audio, sr = result
        return self.play(audio, sr)
