"""
Voice Activity Detection.

Two-layer detection:
  1. Energy gate  — cheap pre-filter; blocks near-silent audio immediately.
  2. WebRTC VAD   — per-frame probabilistic speech detector (if available).

Audio must be 16-bit PCM at 16 kHz (resampled externally if needed).
"""

import logging
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

# WebRTC VAD frame sizes it accepts (ms) at 16 kHz
_WEBRTC_FRAME_MS = 30       # 480 samples
_WEBRTC_AGGRESSIVENESS = 2  # 0 (least) – 3 (most aggressive)

# Energy gate: RMS below this = silence (0–1 float range)
_ENERGY_THRESHOLD = 0.005


def _rms(pcm_float32: np.ndarray) -> float:
    return float(np.sqrt(np.mean(pcm_float32 ** 2)))


class VADEngine:
    """
    Stateful VAD: accumulates a short window of frames and votes on
    whether speech is present. Designed for 16kHz mono float32 chunks.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        speech_threshold: float = 0.6,   # fraction of frames that must be speech
        window_frames: int = 5,          # sliding window size
    ) -> None:
        self._sr = sample_rate
        self._speech_threshold = speech_threshold
        self._window: list[bool] = []
        self._window_size = window_frames
        self._webrtc: Optional[object] = None
        self._frame_samples = int(sample_rate * _WEBRTC_FRAME_MS / 1000)  # 480

        try:
            import webrtcvad
            self._webrtc = webrtcvad.Vad(_WEBRTC_AGGRESSIVENESS)
            logger.debug("WebRTC VAD initialised")
        except ImportError:
            logger.warning("webrtcvad not available; using energy-only VAD")

    def is_speech(self, pcm_float32: np.ndarray) -> bool:
        """
        Returns True if the audio chunk contains speech.
        Input: float32 array at self._sr sample rate.
        """
        # Fast energy gate
        if _rms(pcm_float32) < _ENERGY_THRESHOLD:
            self._window.append(False)
            self._trim_window()
            return False

        if self._webrtc is not None:
            speech = self._webrtc_vote(pcm_float32)
        else:
            # Fallback: energy above threshold counts as speech
            speech = True

        self._window.append(speech)
        self._trim_window()

        if len(self._window) < self._window_size:
            return speech  # not enough history yet

        return (sum(self._window) / len(self._window)) >= self._speech_threshold

    def _webrtc_vote(self, pcm_float32: np.ndarray) -> bool:
        """Slice into WebRTC-sized frames and vote majority."""
        # Convert float32 → int16
        pcm_int16 = (pcm_float32 * 32767).clip(-32768, 32767).astype(np.int16)

        votes = []
        for start in range(0, len(pcm_int16) - self._frame_samples + 1, self._frame_samples):
            frame = pcm_int16[start:start + self._frame_samples]
            if len(frame) == self._frame_samples:
                try:
                    votes.append(self._webrtc.is_speech(frame.tobytes(), self._sr))
                except Exception:
                    pass

        if not votes:
            return True  # default to speech if no frames
        return sum(votes) / len(votes) >= 0.5

    def _trim_window(self) -> None:
        if len(self._window) > self._window_size:
            self._window = self._window[-self._window_size:]

    def reset(self) -> None:
        self._window.clear()
