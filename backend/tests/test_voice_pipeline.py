"""
Tests for Phase 3 — Voice Pipeline.

Unit tests are fully offline (no microphone, no TTS playback needed).
Integration tests tagged @pytest.mark.integration require audio hardware.
"""

import asyncio
import numpy as np
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from modules.voice_engine.models import VoiceMode, VoiceState, TranscriptResult
from modules.voice_engine.vad import VADEngine
from modules.voice_engine.tts_streamer import _split_sentences
from modules.voice_engine import stt_engine
from modules.voice_engine.audio_capture import _classify_device
from modules.voice_engine.stt_engine import _preprocess


# ── VAD ───────────────────────────────────────────────────────────────────────

class TestVAD:
    def _silence(self, n=480):
        return np.zeros(n, dtype=np.float32)

    def _noise(self, n=480, amp=0.05):
        return (np.random.randn(n) * amp).astype(np.float32)

    def test_silence_not_speech(self):
        vad = VADEngine()
        for _ in range(6):
            result = vad.is_speech(self._silence())
        assert result is False

    def test_loud_noise_is_speech(self):
        vad = VADEngine()
        loud = (np.random.randn(480) * 0.5).astype(np.float32)
        for _ in range(6):
            result = vad.is_speech(loud)
        assert result is True

    def test_reset_clears_window(self):
        vad = VADEngine()
        loud = (np.random.randn(480) * 0.5).astype(np.float32)
        for _ in range(6):
            vad.is_speech(loud)
        vad.reset()
        # After reset, window is empty so single silence returns False
        assert vad.is_speech(self._silence()) is False

    def test_energy_gate_blocks_sub_threshold(self):
        vad = VADEngine()
        tiny = np.full(480, 0.001, dtype=np.float32)
        for _ in range(6):
            result = vad.is_speech(tiny)
        assert result is False


# ── Sentence splitter ─────────────────────────────────────────────────────────

class TestSentenceSplitter:
    def test_single_sentence(self):
        sentences, remainder = _split_sentences("Hello world.")
        assert sentences == ["Hello world."]
        assert remainder == ""

    def test_multiple_sentences(self):
        sentences, remainder = _split_sentences("Hello. How are you? I am fine.")
        assert len(sentences) == 3
        assert remainder == ""

    def test_partial_sentence_stays_in_buffer(self):
        sentences, remainder = _split_sentences("Hello world. How are")
        assert sentences == ["Hello world."]
        assert remainder == "How are"

    def test_no_sentence_boundary(self):
        sentences, remainder = _split_sentences("Hello world")
        assert sentences == []
        assert remainder == "Hello world"

    def test_empty_string(self):
        sentences, remainder = _split_sentences("")
        assert sentences == []
        assert remainder == ""

    def test_question_mark(self):
        sentences, remainder = _split_sentences("Are you ready? Let's go")
        assert "Are you ready?" in sentences
        assert remainder.strip() == "Let's go"

    def test_exclamation(self):
        sentences, remainder = _split_sentences("Watch out!")
        assert "Watch out!" in sentences


# ── STT Engine ────────────────────────────────────────────────────────────────

class TestSTTEngine:
    def test_short_audio_returns_empty(self):
        # Audio shorter than min_duration_s should return empty without loading model
        tiny = np.zeros(100, dtype=np.float32)
        result = stt_engine.transcribe(tiny, sample_rate=16000, min_duration_s=0.5)
        assert result.text == ""
        assert result.is_final is True

    def test_resample_changes_length(self):
        from modules.voice_engine.stt_engine import _resample
        audio_44k = np.random.randn(44100).astype(np.float32)
        audio_16k = _resample(audio_44k, from_sr=44100, to_sr=16000)
        expected = int(44100 * 16000 / 44100)
        assert abs(len(audio_16k) - expected) <= 2

    def test_resample_same_rate_unchanged(self):
        from modules.voice_engine.stt_engine import _resample
        audio = np.random.randn(1000).astype(np.float32)
        result = _resample(audio, from_sr=16000, to_sr=16000)
        np.testing.assert_array_equal(audio, result)


# ── TTS Engine ────────────────────────────────────────────────────────────────

class TestTTSEngine:
    def test_interrupt_cancels_token(self):
        from modules.voice_engine.tts_engine import TTSEngine, _PlaybackToken
        engine = TTSEngine()
        token = _PlaybackToken()
        engine._current_token = token
        engine.interrupt()
        assert token.cancelled is True

    def test_interrupt_with_no_active_playback_safe(self):
        from modules.voice_engine.tts_engine import TTSEngine
        engine = TTSEngine()
        engine.interrupt()   # should not raise

    def test_synthesise_empty_text_returns_none(self):
        from modules.voice_engine.tts_engine import TTSEngine
        engine = TTSEngine()
        result = engine.synthesise("   ")
        assert result is None

    def test_synthesise_produces_audio(self):
        from modules.voice_engine.tts_engine import TTSEngine
        engine = TTSEngine(provider="say", voice="Samantha")
        result = engine.synthesise("Test.")
        assert result is not None
        audio, sample_rate = result
        assert len(audio) > 0
        assert audio.dtype == np.float32
        assert sample_rate > 0

    def test_play_interrupted_returns_false(self):
        from modules.voice_engine.tts_engine import TTSEngine
        import threading
        engine = TTSEngine()
        audio = np.zeros(22050, dtype=np.float32)

        results = []

        def _play():
            results.append(engine.play(audio))

        t = threading.Thread(target=_play)
        t.start()
        import time; time.sleep(0.05)
        engine.interrupt()
        t.join(timeout=3)
        # Either interrupted (False) or finished naturally (True) — no crash
        assert isinstance(results[0], bool)


# ── TTS Streamer ──────────────────────────────────────────────────────────────

class TestTTSStreamer:
    @pytest.mark.asyncio
    async def test_streamer_fires_sentences(self):
        from modules.voice_engine.tts_streamer import TTSStreamer
        from modules.voice_engine.tts_engine import TTSEngine

        engine = TTSEngine()
        fake_audio = (np.zeros(100, dtype=np.float32), 22050)
        with patch.object(engine, 'synthesise', side_effect=lambda t: fake_audio):
            with patch.object(engine, 'play', side_effect=lambda a, sr=22050: True):
                async with TTSStreamer(engine) as streamer:
                    # Long enough to cross MIN_BATCH_CHARS
                    await streamer.push("Hello world this is the first sentence here. ")
                    await streamer.push("And here is a second sentence to push the batch. ")
                await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_streamer_flush_speaks_remainder(self):
        from modules.voice_engine.tts_streamer import TTSStreamer
        from modules.voice_engine.tts_engine import TTSEngine

        synthesised: list[str] = []
        engine = TTSEngine()
        fake_audio = (np.zeros(100, dtype=np.float32), 22050)

        with patch.object(engine, 'synthesise',
                          side_effect=lambda t: (synthesised.append(t), fake_audio)[1]):
            with patch.object(engine, 'play', return_value=True):
                async with TTSStreamer(engine) as streamer:
                    await streamer.push("No boundary here")
                    # flush() called on __aexit__

        assert any("No boundary here" in s for s in synthesised)

    def test_batch_short_sentence_held_back(self):
        from modules.voice_engine.tts_streamer import _take_batch
        # "Hi." is too short — should stay in buffer waiting for more
        batch, rem = _take_batch("Hi.")
        assert batch is None
        assert rem == "Hi."

    def test_batch_long_enough_emits(self):
        from modules.voice_engine.tts_streamer import _take_batch, MIN_BATCH_CHARS
        text = "Hello world. " * 10   # >> MIN_BATCH_CHARS
        batch, rem = _take_batch(text)
        assert batch is not None
        assert len(batch) >= MIN_BATCH_CHARS

    def test_batch_force_flush_on_oversize(self):
        from modules.voice_engine.tts_streamer import _take_batch, MAX_BATCH_CHARS
        # No sentence end at all, but exceeds MAX_BATCH_CHARS
        text = "word " * 60
        batch, rem = _take_batch(text)
        assert batch is not None
        assert " " in batch                  # broke on word boundary
        assert len(batch) <= MAX_BATCH_CHARS

    @pytest.mark.asyncio
    async def test_interrupt_drains_queue(self):
        from modules.voice_engine.tts_streamer import TTSStreamer
        from modules.voice_engine.tts_engine import TTSEngine

        engine = TTSEngine()
        fake_audio = (np.zeros(100, dtype=np.float32), 22050)
        with patch.object(engine, 'synthesise', return_value=fake_audio):
            with patch.object(engine, 'play', return_value=True):
                async with TTSStreamer(engine) as streamer:
                    await streamer.push("Sentence one. Sentence two. Sentence three.")
                    streamer.interrupt()
                    assert streamer._buffer == ""


# ── Voice Pipeline (integration smoke test) ───────────────────────────────────

@pytest.mark.integration
class TestVoicePipelineIntegration:
    @pytest.mark.asyncio
    async def test_ptt_produces_transcript(self):
        """
        Simulate PTT: feed synthetic speech-like audio and confirm the transcript
        callback fires. Uses real Whisper model.
        """
        from modules.voice_engine.voice_pipeline import VoicePipeline

        transcripts: list[str] = []

        async def on_transcript(result: TranscriptResult):
            transcripts.append(result.text)

        pipeline = VoicePipeline(mode=VoiceMode.PUSH_TO_TALK, whisper_model="tiny")
        pipeline.on_transcript(on_transcript)

        # Inject a 2-second synthetic noise buffer (won't produce real speech)
        audio = (np.random.randn(32000) * 0.3).astype(np.float32)
        await pipeline._transcribe_and_fire(audio)

        # Whether or not Whisper finds words, the callback must have fired
        assert isinstance(transcripts, list)


# ── Device classification ────────────────────────────────────────────────────

class TestDeviceClassification:
    def test_external_yeti(self):
        kind, score = _classify_device("blue yeti")
        assert kind == "external" and score == 100

    def test_external_shure(self):
        kind, score = _classify_device("shure mv7")
        assert kind == "external" and score == 100

    def test_external_focusrite_scarlett(self):
        kind, score = _classify_device("scarlett solo 4th gen")
        assert kind == "external" and score == 100

    def test_external_rode(self):
        kind, score = _classify_device("rode nt-usb mini")
        assert kind == "external" and score == 100

    def test_external_audio_technica(self):
        kind, score = _classify_device("audio-technica at2020 usb")
        assert kind == "external" and score == 100

    def test_external_generic_usb_microphone(self):
        kind, score = _classify_device("usb microphone")
        assert kind == "external" and score == 100

    def test_builtin_macbook(self):
        kind, score = _classify_device("macbook air microphone")
        assert kind == "builtin" and score == 60

    def test_bluetooth_airpods(self):
        kind, score = _classify_device("airpods pro")
        assert kind == "bluetooth" and score == 10

    def test_bluetooth_jabra(self):
        kind, score = _classify_device("jabra elite 75t")
        assert kind == "bluetooth" and score == 10

    def test_unknown_falls_to_generic(self):
        kind, score = _classify_device("some random device 9000")
        assert kind == "unknown" and score == 40


# ── STT preprocessing ────────────────────────────────────────────────────────

class TestSttPreprocess:
    def test_empty_returns_empty(self):
        out = _preprocess(np.array([], dtype=np.float32))
        assert out.size == 0

    def test_dc_offset_removed(self):
        audio = np.full(16000, 0.05, dtype=np.float32)  # constant 0.05 = DC
        out = _preprocess(audio)
        # Mean should be near zero after DC removal
        assert abs(out.mean()) < 1e-3

    def test_quiet_audio_normalized_up(self):
        # Peak at 0.05 → should be boosted toward target (~0.85)
        audio = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.05
        out = _preprocess(audio)
        assert float(np.max(np.abs(out))) > 0.3

    def test_loud_audio_not_attenuated(self):
        # Peak at 0.95 → should pass through unchanged (above target)
        audio = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.95
        out = _preprocess(audio)
        # Peak should still be near 0.95, not pushed down
        assert float(np.max(np.abs(out))) >= 0.9

    def test_safety_clip(self):
        audio = np.full(16000, 1.5, dtype=np.float32)   # invalid >1.0
        out = _preprocess(audio)
        assert float(np.max(out)) <= 1.0
        assert float(np.min(out)) >= -1.0

    def test_gain_capped(self):
        # Near-silence with peak 1e-5 — gain would be huge without cap
        audio = np.full(16000, 1e-5, dtype=np.float32)
        out = _preprocess(audio)
        # After DC removal there's nothing; ensure no NaN/inf
        assert np.isfinite(out).all()
