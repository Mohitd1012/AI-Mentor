"""
Voice Pipeline — orchestrates capture → VAD → STT → AI → TTS.

Threading model
───────────────
sounddevice callback  →  runs in a C-level audio thread (NOT the event loop)
ptt_start / ptt_stop  →  called from the asyncio WS handler (IN the loop)
_transcribe_and_fire  →  coroutine, always scheduled via loop.create_task()

The key invariant: asyncio work is NEVER called directly from the audio
callback thread. Instead we use loop.call_soon_threadsafe() to hand work
back to the event loop.
"""

import asyncio
import logging
from typing import Callable, Awaitable, Optional

import numpy as np

from modules.voice_engine.models import VoiceMode, VoiceState, TranscriptResult
from modules.voice_engine.audio_capture import (
    AudioCapture, RecordingBuffer, find_best_input_device,
)
from modules.voice_engine.vad import VADEngine
from modules.voice_engine import stt_engine
from modules.voice_engine.tts_engine import TTSEngine
from modules.voice_engine.tts_streamer import TTSStreamer

logger = logging.getLogger(__name__)

_SILENCE_TIMEOUT_S   = 1.2
_MIN_SPEECH_DURATION = 0.4
_MAX_RECORDING_S     = 30.0

TranscriptCallback = Callable[[TranscriptResult], Awaitable[None]]
StateCallback      = Callable[[VoiceState], Awaitable[None]]


class VoicePipeline:
    def __init__(
        self,
        mode: VoiceMode = VoiceMode.PUSH_TO_TALK,
        whisper_model: str = "small.en",
        tts_provider: str = "kokoro",
        tts_voice: str = "af_heart",
        tts_rate: int = 175,
    ) -> None:
        self._mode    = mode
        self._state   = VoiceState.IDLE
        # Backend-specific kwargs: `say` takes rate, kokoro does not
        backend_kwargs = {"voice": tts_voice}
        if tts_provider == "say":
            backend_kwargs["rate"] = tts_rate
        self._tts     = TTSEngine(provider=tts_provider, **backend_kwargs)
        self._vad     = VADEngine()
        self._buffer  = RecordingBuffer()
        self._capture: Optional[AudioCapture] = None
        self._loop:    Optional[asyncio.AbstractEventLoop] = None

        self._on_transcript:   Optional[TranscriptCallback] = None
        self._on_state_change: Optional[StateCallback] = None

        self._ptt_active     = False
        self._speech_active  = False
        self._silence_frames = 0
        self._silence_limit  = int(_SILENCE_TIMEOUT_S / 0.030)

        stt_engine.load_model(whisper_model)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_mode(self, mode: VoiceMode) -> None:
        self._mode = mode
        logger.info("[voice] mode → %s", mode.value)

    def on_transcript(self, cb: TranscriptCallback) -> None:
        self._on_transcript = cb

    def on_state_change(self, cb: StateCallback) -> None:
        self._on_state_change = cb

    async def start(self) -> None:
        if self._mode == VoiceMode.OFF:
            return
        # Capture the running event loop NOW (called from async context)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[voice] start() called outside async context — voice disabled")
            return

        # Run blocking device probe in executor so we don't stall the event loop
        device = await self._loop.run_in_executor(None, find_best_input_device)
        self._capture = AudioCapture(
            on_chunk=self._on_audio_chunk,
            loop=self._loop,
            device=device,
        )
        self._capture.start()
        logger.info("[voice] pipeline started (mode=%s)", self._mode.value)

    def stop(self) -> None:
        if self._capture:
            self._capture.stop()
            self._capture = None
        self._tts.interrupt()
        self._buffer.clear()
        logger.info("[voice] pipeline stopped")

    def ptt_start(self) -> None:
        """Called from async WS handler — safe to use asyncio directly."""
        if self._mode != VoiceMode.PUSH_TO_TALK:
            return
        self._ptt_active = True
        self._buffer.clear()
        self._schedule(_set_state_coro(self, VoiceState.LISTENING))
        logger.debug("[voice] PTT started")

    def ptt_stop(self) -> None:
        """Called from async WS handler."""
        if not self._ptt_active:
            return
        self._ptt_active = False
        audio = self._buffer.consume()
        self._schedule(self._transcribe_and_fire(audio))

    def interrupt_speech(self) -> None:
        self._tts.interrupt()

    def get_tts_engine(self) -> TTSEngine:
        return self._tts

    def get_tts_streamer(self) -> TTSStreamer:
        return TTSStreamer(self._tts)

    # ── Audio callback (sounddevice thread — NO direct asyncio allowed) ────────

    def _on_audio_chunk(self, chunk: np.ndarray) -> None:
        # Interrupt TTS when user speaks during AI response
        if self._state == VoiceState.SPEAKING and self._vad.is_speech(chunk):
            self._tts.interrupt()

        if self._mode == VoiceMode.PUSH_TO_TALK:
            if self._ptt_active:
                self._buffer.append(chunk)

        elif self._mode == VoiceMode.ALWAYS_LISTENING:
            self._handle_always_on(chunk)

    def _handle_always_on(self, chunk: np.ndarray) -> None:
        """Runs in audio thread — only uses threadsafe primitives."""
        is_speech = self._vad.is_speech(chunk)

        if is_speech:
            self._silence_frames = 0
            if not self._speech_active:
                self._speech_active = True
                self._buffer.clear()
                # ← threadsafe: hands coroutine to event loop
                self._threadsafe(_set_state_coro(self, VoiceState.LISTENING))
            self._buffer.append(chunk)

        elif self._speech_active:
            self._silence_frames += 1
            self._buffer.append(chunk)

            if (self._silence_frames >= self._silence_limit
                    or self._buffer.duration_s() >= _MAX_RECORDING_S):
                self._speech_active  = False
                self._silence_frames = 0
                audio = self._buffer.consume()
                self._threadsafe(self._transcribe_and_fire(audio))

    # ── Scheduling helpers ────────────────────────────────────────────────────

    def _schedule(self, coro) -> None:
        """Schedule a coroutine from the event loop thread."""
        if self._loop:
            self._loop.create_task(coro)
        else:
            logger.warning("[voice] _schedule: no event loop stored")

    def _threadsafe(self, coro) -> None:
        """Schedule a coroutine from a non-event-loop thread."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.create_task, coro)
        else:
            logger.warning("[voice] _threadsafe: no event loop stored")

    # ── Coroutines ────────────────────────────────────────────────────────────

    async def _transcribe_and_fire(self, audio: np.ndarray) -> None:
        if len(audio) / 16000 < _MIN_SPEECH_DURATION:
            await self._set_state(VoiceState.IDLE)
            return

        await self._set_state(VoiceState.TRANSCRIBING)
        loop = asyncio.get_running_loop()

        try:
            result: TranscriptResult = await loop.run_in_executor(
                None, stt_engine.transcribe, audio
            )
        except Exception:
            logger.exception("[voice] STT error")
            await self._set_state(VoiceState.IDLE)
            return

        await self._set_state(VoiceState.IDLE)

        if result.text and self._on_transcript:
            logger.info("[voice] transcript: '%s'", result.text)
            await self._on_transcript(result)

    async def _set_state(self, state: VoiceState) -> None:
        if self._state == state:
            return
        self._state = state
        if self._on_state_change:
            try:
                await self._on_state_change(state)
            except Exception:
                logger.exception("[voice] state change callback error")

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def mode(self) -> VoiceMode:
        return self._mode


# Helper so _threadsafe can pass a coroutine without a closure
async def _set_state_coro(pipeline: VoicePipeline, state: VoiceState) -> None:
    await pipeline._set_state(state)
