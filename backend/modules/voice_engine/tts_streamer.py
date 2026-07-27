"""
Streaming TTS — smooth, pipelined sentence playback.

Two-stage pipeline runs synthesis in parallel with playback:

    text chunks ──► [sentence batcher] ──► synth queue ──► [synth worker]
                                                                  │
                                                                  ▼
                                                            audio queue
                                                                  │
                                                                  ▼
                                                          [play worker] ──► speaker

  • Sentence batcher accumulates incoming chunks until it has a meaningful
    chunk (≥ MIN_BATCH_CHARS or a sentence end) to keep `say` overhead low.
  • Synth worker pre-renders the next batch while the current one plays,
    so playback is continuous (no audible synth-gap between sentences).
"""

import asyncio
import logging
import re
from typing import Optional

import numpy as np

from modules.voice_engine.tts_engine import TTSEngine

logger = logging.getLogger(__name__)

# Sentence-ending punctuation (skip abbreviations like Dr. and numbers like 3.14)
_SENTENCE_END = re.compile(r'(?<![A-Z][a-z])(?<!\d)[.!?]+(?:\s|$)')

# Batching thresholds
MIN_BATCH_CHARS = 80    # batch sentences until total text is meaningful
MAX_BATCH_CHARS = 220   # but don't wait forever before speaking


def _next_sentence_end(text: str) -> Optional[int]:
    """Return the index just after the next sentence-ending punctuation."""
    m = _SENTENCE_END.search(text)
    return m.end() if m else None


def _split_sentences(text: str) -> tuple[list[str], str]:
    """
    Backwards-compatible splitter (used by tests).
    Returns (complete_sentences, remainder).
    """
    sentences: list[str] = []
    remainder = text
    while True:
        idx = _next_sentence_end(remainder)
        if idx is None:
            break
        sentence = remainder[:idx].strip()
        if sentence:
            sentences.append(sentence)
        remainder = remainder[idx:]
    return sentences, remainder


def _take_batch(buffer: str) -> tuple[Optional[str], str]:
    """
    Extract one batch from the buffer, or None if not enough text yet.

    A batch is at least MIN_BATCH_CHARS long AND ends on a sentence boundary,
    OR is at least MAX_BATCH_CHARS long (forced).

    Returns (batch_or_none, remainder).
    """
    if not buffer:
        return None, buffer

    # If we're way past MAX_BATCH_CHARS, force-flush at next sentence end
    # (or word boundary if no sentence end found)
    if len(buffer) >= MAX_BATCH_CHARS:
        idx = _next_sentence_end(buffer)
        if idx is None:
            # No sentence end in sight — break on last word boundary
            cut = buffer.rfind(" ", 0, MAX_BATCH_CHARS)
            if cut <= 0:
                return None, buffer  # one long word — wait for space
            return buffer[:cut].strip(), buffer[cut:].lstrip()
        return buffer[:idx].strip(), buffer[idx:].lstrip()

    # Normal path: accumulate sentences until we hit MIN_BATCH_CHARS
    accum_end = 0
    cursor = 0
    while cursor < len(buffer):
        idx = _next_sentence_end(buffer[cursor:])
        if idx is None:
            break
        accum_end = cursor + idx
        if accum_end >= MIN_BATCH_CHARS:
            return buffer[:accum_end].strip(), buffer[accum_end:].lstrip()
        cursor = accum_end

    return None, buffer


class TTSStreamer:
    """
    Pipelined streaming TTS.

    Stage 1 (synth worker): dequeues text batches → synthesises audio
    Stage 2 (play worker):  dequeues audio → plays back

    Stages run concurrently so synthesis of batch N+1 overlaps playback of
    batch N — eliminating perceptible gaps between sentences.
    """

    def __init__(self, engine: TTSEngine) -> None:
        self._engine = engine
        self._buffer = ""
        self._synth_queue: asyncio.Queue = asyncio.Queue()
        self._play_queue: asyncio.Queue  = asyncio.Queue(maxsize=4)
        self._synth_task: Optional[asyncio.Task] = None
        self._play_task:  Optional[asyncio.Task] = None
        self._active = False

    async def __aenter__(self):
        self._active = True
        self._synth_task = asyncio.create_task(self._synth_worker(), name="tts_synth")
        self._play_task  = asyncio.create_task(self._play_worker(),  name="tts_play")
        return self

    async def __aexit__(self, *_):
        await self.flush()
        self._active = False
        await self._synth_queue.put(None)  # signal synth worker to drain
        if self._synth_task:
            try:
                await asyncio.wait_for(self._synth_task, timeout=20.0)
            except asyncio.TimeoutError:
                self._synth_task.cancel()
        await self._play_queue.put(None)   # signal play worker to drain
        if self._play_task:
            try:
                await asyncio.wait_for(self._play_task, timeout=30.0)
            except asyncio.TimeoutError:
                self._play_task.cancel()

    async def push(self, chunk: str) -> None:
        """Called with each streaming text chunk from the AI router."""
        self._buffer += chunk
        # Pull as many ready batches as we can
        while True:
            batch, self._buffer = _take_batch(self._buffer)
            if batch is None:
                break
            await self._synth_queue.put(batch)

    async def flush(self) -> None:
        """Emit any remaining buffered text as a final batch."""
        tail = self._buffer.strip()
        if tail:
            await self._synth_queue.put(tail)
            self._buffer = ""

    def interrupt(self) -> None:
        """Stop current playback and drain all queues."""
        self._engine.interrupt()
        for q in (self._synth_queue, self._play_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self._buffer = ""

    # ── Workers ───────────────────────────────────────────────────────────────

    async def _synth_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            text = await self._synth_queue.get()
            if text is None:
                await self._play_queue.put(None)
                return
            try:
                audio_result = await loop.run_in_executor(
                    None, self._engine.synthesise, text
                )
                if audio_result is not None:
                    await self._play_queue.put(audio_result)
            except Exception:
                logger.exception("[tts] synth worker error: %.40s", text)

    async def _play_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            item = await self._play_queue.get()
            if item is None:
                return
            audio, sr = item
            try:
                await loop.run_in_executor(None, self._engine.play, audio, sr)
            except Exception:
                logger.exception("[tts] play worker error")
