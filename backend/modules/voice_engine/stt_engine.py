"""
Speech-to-Text engine — faster-whisper (local, runs on CPU).

Loads the model once at startup and transcribes audio buffers on demand.
All heavy calls are synchronous; callers must run in an executor.

Model size guide (faster-whisper, int8 quantization on Apple Silicon CPU):
    tiny.en   ~40 MB   transcribe 3s in ~250 ms   noticeably worse on noise
    base      ~145 MB  transcribe 3s in ~500 ms   good for clean audio
    small.en  ~480 MB  transcribe 3s in ~900 ms   ★ much better on noise, accents, fast speech
    medium.en ~1.5 GB  transcribe 3s in ~2.5 s    even better; usually overkill
"""

import logging
import numpy as np
from typing import Optional

from modules.voice_engine.models import TranscriptResult

logger = logging.getLogger(__name__)

# Lazy-loaded model + remembered size
_model = None
_model_size: str = "small.en"   # better default than `base`

# Audio preprocessing knobs
_TARGET_PEAK = 0.85         # normalize quiet/external-mic audio up to this peak
_DC_OFFSET_FIX = True       # subtract mean to remove DC bias from some mics


def load_model(model_size: str = "small.en") -> None:
    """Pre-load the Whisper model. Call once at startup to avoid first-call latency."""
    global _model, _model_size
    _model_size = model_size
    _get_model()


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        logger.info(
            "Loading Whisper model '%s' (first call may download the weights)",
            _model_size,
        )
        _model = WhisperModel(
            _model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=0,  # let faster-whisper pick (0 = auto, uses all cores)
        )
        logger.info("Whisper model loaded")
    return _model


def _preprocess(audio: np.ndarray) -> np.ndarray:
    """
    Light audio cleanup before STT:
      • Remove DC offset (some USB mics introduce one)
      • Peak-normalize to TARGET_PEAK so quiet external mics get a boost
        without crushing already-loud audio
    """
    if audio.size == 0:
        return audio

    out = audio.astype(np.float32, copy=False)

    if _DC_OFFSET_FIX:
        mean = float(out.mean())
        if abs(mean) > 1e-4:
            out = out - mean

    peak = float(np.max(np.abs(out)))
    if peak > 0.0 and peak < _TARGET_PEAK:
        # Boost soft audio toward target peak. Don't attenuate loud audio —
        # leaves headroom and avoids amplifying already-saturated clips.
        gain = _TARGET_PEAK / peak
        # Cap gain so a near-silent room doesn't get blown up into pure noise
        gain = min(gain, 8.0)
        out = out * gain

    # Final safety clip
    np.clip(out, -1.0, 1.0, out=out)
    return out


def transcribe(
    audio_float32: np.ndarray,
    sample_rate: int = 16000,
    language: Optional[str] = "en",
    min_duration_s: float = 0.3,
) -> TranscriptResult:
    """
    Transcribe a numpy float32 audio array.

    audio_float32 must be at `sample_rate` Hz, mono.
    Returns TranscriptResult with empty text if audio is too short.
    """
    duration = len(audio_float32) / sample_rate
    if duration < min_duration_s:
        return TranscriptResult(text="", is_final=True, duration_s=duration)

    model = _get_model()

    # Resample to 16kHz if needed
    if sample_rate != 16000:
        audio_float32 = _resample(audio_float32, sample_rate, 16000)

    # Clean up before STT — big help for external mics
    audio_float32 = _preprocess(audio_float32)

    segments, info = model.transcribe(
        audio_float32,
        beam_size=5,
        language=language,
        # Use VAD to drop leading/trailing silence and breaks within the clip
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 250,
            "speech_pad_ms": 200,           # keep a little context around speech
        },
        # Suppress hallucinated leftovers like "Thanks for watching!" from
        # silence at the end of clips
        condition_on_previous_text=False,
        no_speech_threshold=0.5,
    )

    text = " ".join(s.text for s in segments).strip()
    return TranscriptResult(
        text=text,
        is_final=True,
        language=info.language,
        duration_s=duration,
    )


def _resample(audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
    """Linear resample. Adequate for speech; not audiophile-grade."""
    if from_sr == to_sr:
        return audio
    ratio = to_sr / from_sr
    new_length = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, new_length)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
