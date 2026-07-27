"""
Microphone audio capture — produces 16kHz float32 audio buffers.

Key design decisions:
  • Finds the best available input device: prefers internal mic over Bluetooth
    (BT mics are commonly silent when in A2DP mode)
  • Stores the asyncio event loop at construction time so the audio callback
    thread can schedule coroutines safely via loop.call_soon_threadsafe()
"""

import asyncio
import logging
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

CAPTURE_SAMPLE_RATE = 16000
CAPTURE_CHANNELS    = 1
CHUNK_DURATION_S    = 0.03       # 30ms → 480 samples (WebRTC VAD frame size)
CHUNK_SAMPLES       = int(CAPTURE_SAMPLE_RATE * CHUNK_DURATION_S)

AudioChunkCallback = Callable[[np.ndarray], None]

# Name fragments that strongly indicate a specific device kind.
_BT_HINTS = (
    "airpods", "airdopes", "buds", "headset", "beats", "jabra", "bose",
    "sony wh", "anc", "bluetooth",
)
_BUILTIN_HINTS = (
    "macbook", "imac", "built-in", "internal",
)
# Common high-quality external microphones / audio interfaces.
_EXTERNAL_HINTS = (
    "yeti", "blue ",            # Blue Yeti / Blue mics
    "shure", "rode", "rØde",
    "audio-technica", "at2020", "at2035", "at4040",
    "elgato", "wave",
    "samson", "snowball",
    "scarlett", "focusrite",
    "behringer", "presonus", "motu",
    "zoom h", "zoom u",         # Zoom handhelds / interfaces
    "evo ",                     # Audient EVO
    "usb microphone", "usb audio", "usb mic",
    "podcaster", "movo",
)


def _classify_device(name_lower: str) -> tuple[str, int]:
    """
    Returns (kind, base_score) for a device name. Higher score = preferred.

      external (USB / audio interface)  → 100
      built-in (MacBook/iMac mic)       → 60
      generic / unknown                  → 40
      bluetooth                          → 10
    """
    for hint in _EXTERNAL_HINTS:
        if hint in name_lower:
            return "external", 100
    for hint in _BT_HINTS:
        if hint in name_lower:
            return "bluetooth", 10
    for hint in _BUILTIN_HINTS:
        if hint in name_lower:
            return "builtin", 60
    return "unknown", 40


def list_input_devices() -> list[dict]:
    """
    Returns every input device with its classification + a quick RMS probe.
    Used by the REST endpoint and by `find_best_input_device`.
    """
    out: list[dict] = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] == 0:
            continue
        name = d["name"]
        kind, score = _classify_device(name.lower())
        rms  = _probe_device(i)
        # Bonus score for higher input channel counts (audio interfaces) and
        # for actually producing signal during the probe.
        if rms > 0.0001:
            score += 30
        if rms > 0.01:
            score += 20      # genuinely loud signal — likely the active mic
        if d["max_input_channels"] >= 2:
            score += 5
        out.append({
            "index": i,
            "name":  name,
            "kind":  kind,
            "channels": d["max_input_channels"],
            "sample_rate": int(d["default_samplerate"]),
            "rms": round(rms, 6),
            "score": score,
            "is_responsive": rms > 0.0001,
        })
    return out


def find_best_input_device() -> Optional[int]:
    """
    Return the device index of the best available microphone.

    Scoring priorities, highest first:
      • External USB mic / audio interface that's producing signal
      • Built-in microphone that's producing signal
      • Any other responsive device
      • Bluetooth devices (last resort — their mic profile is often muted)
    """
    devices = list_input_devices()
    if not devices:
        logger.warning("No input devices found at all; using system default")
        return None

    # Sort by score desc; log the picks for debuggability
    devices.sort(key=lambda d: d["score"], reverse=True)
    for d in devices:
        logger.debug("Device [%d] %-35s kind=%-9s rms=%.6f score=%d",
                     d["index"], d["name"], d["kind"], d["rms"], d["score"])

    # Pick the highest-scoring device that's responsive
    for d in devices:
        if d["is_responsive"]:
            logger.info(
                "Selected input device [%d] %s (%s, rms=%.4f)",
                d["index"], d["name"], d["kind"], d["rms"],
            )
            return d["index"]

    # Nothing was responsive — fall back to the highest scored anyway so we
    # don't get stuck on an even worse system default.
    fallback = devices[0]
    logger.warning(
        "No responsive input device; falling back to highest-scored: [%d] %s",
        fallback["index"], fallback["name"],
    )
    return fallback["index"]


def _probe_device(device_idx: int, duration_s: float = 0.25) -> float:
    """Record a short burst and return the RMS. Returns 0 on failure."""
    try:
        n = int(CAPTURE_SAMPLE_RATE * duration_s)
        rec = sd.rec(n, samplerate=CAPTURE_SAMPLE_RATE, channels=1,
                     dtype="float32", device=device_idx, blocking=True)
        return float(np.sqrt(np.mean(rec ** 2)))
    except Exception:
        return 0.0


class AudioCapture:
    """
    Wraps sounddevice InputStream.
    Calls `on_chunk(float32_array)` for every 30ms audio slice.

    `loop` must be the running asyncio event loop — stored so that callbacks
    scheduled from the sounddevice thread can use call_soon_threadsafe().
    """

    def __init__(
        self,
        on_chunk: AudioChunkCallback,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        device: Optional[int] = None,
    ) -> None:
        self._on_chunk = on_chunk
        self._loop     = loop
        self._device   = device
        self._stream: Optional[sd.InputStream] = None
        self._active   = False

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._stream = sd.InputStream(
            samplerate=CAPTURE_SAMPLE_RATE,
            channels=CAPTURE_CHANNELS,
            dtype="float32",
            blocksize=CHUNK_SAMPLES,
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()
        logger.info("[audio] capture started @ %dHz device=%s",
                    CAPTURE_SAMPLE_RATE, self._device)

    def stop(self) -> None:
        self._active = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("[audio] capture stopped")

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("[audio] stream status: %s", status)
        if self._active:
            self._on_chunk(indata[:, 0].copy())


class RecordingBuffer:
    """Thread-safe ring buffer for accumulating audio chunks."""

    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    def append(self, chunk: np.ndarray) -> None:
        with self._lock:
            self._chunks.append(chunk)

    def consume(self) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.array([], dtype=np.float32)
            audio = np.concatenate(self._chunks)
            self._chunks.clear()
            return audio

    def duration_s(self) -> float:
        with self._lock:
            total = sum(len(c) for c in self._chunks)
        return total / CAPTURE_SAMPLE_RATE

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
