#!/usr/bin/env python3
"""
Live VAD test — prints a rolling indicator of whether the VAD
considers each 30ms chunk speech vs silence.

Use this to confirm:
  • Your mic is producing signal (RMS column non-zero when you speak)
  • The VAD agrees it's speech (S/. column)
  • You learn what your speaking volume looks like to the engine

Press Ctrl-C to stop.
"""

import asyncio
import sys
import time

import numpy as np

sys.path.insert(0, "backend")

from modules.voice_engine.audio_capture import (
    AudioCapture, find_best_input_device,
)
from modules.voice_engine.vad import VADEngine


async def main():
    print("Probing input devices…")
    device = find_best_input_device()
    if device is None:
        print("⚠  No working input device found")
        return

    vad = VADEngine()
    print(f"✓ Using device {device}")
    print(f"\n{'time':>6}  {'rms':>8}  {'speech?':>8}  bar")
    print("─" * 60)

    start = time.time()

    def on_chunk(chunk: np.ndarray):
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        is_speech = vad.is_speech(chunk)
        # Visual bar (RMS → 0-30 chars)
        bar_len = min(int(rms * 800), 30)
        bar = ("█" * bar_len).ljust(30)
        marker = "S" if is_speech else "."
        # Throttle output to ~10 lines/sec
        if int((time.time() - start) * 10) % 3 == 0:
            print(f"{time.time() - start:6.1f}  {rms:8.5f}  {marker:>8}  {bar}",
                  flush=True)

    loop = asyncio.get_running_loop()
    capture = AudioCapture(on_chunk=on_chunk, loop=loop, device=device)
    capture.start()

    try:
        await asyncio.sleep(20)   # 20s session
    except asyncio.CancelledError:
        pass
    finally:
        capture.stop()
        print("\n✓ Stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✓ Stopped")
