#!/usr/bin/env python3
"""
End-to-end test for always-listening mode.

Starts a WebSocket session, switches voice mode to ALWAYS_LISTENING,
then prints every event the backend emits for 30 seconds.

Speak into your microphone during that window. Expected sequence:
   voice_state: idle      → listening (when speech starts)
   voice_state: listening → transcribing (after 1.2s silence)
   transcript:  "<your words>"
   status:      thinking → speaking → idle
   chunk:       <AI response streaming>

Usage:
   .venv/bin/python scripts/test_always_listening.py
"""

import asyncio
import json
import sys
import websockets


URL = "ws://localhost:8765/ws"


async def main():
    try:
        async with websockets.connect(URL) as ws:
            print(f"✓ Connected to {URL}")

            # Switch to always-listening mode
            await ws.send(json.dumps({
                "type": "set_voice_mode",
                "mode": "always_listening",
            }))
            print("✓ Sent set_voice_mode=always_listening")
            print("\n🎙  SPEAK NOW — recording for 30 seconds")
            print("─" * 60)

            end_at = asyncio.get_event_loop().time() + 30
            while asyncio.get_event_loop().time() < end_at:
                remaining = end_at - asyncio.get_event_loop().time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break

                msg = json.loads(raw)
                t = msg.get("type")

                if t == "voice_state":
                    state = msg.get("state")
                    icon = {"listening": "🔴", "transcribing": "🟡", "idle": "⚪"}.get(state, "•")
                    print(f"{icon}  voice_state → {state}")
                elif t == "transcript":
                    print(f"📝  TRANSCRIPT: {msg.get('text')!r}")
                elif t == "status":
                    print(f"💭  ai status: {msg.get('state')}")
                elif t == "chunk":
                    if msg.get("done"):
                        print("✓  ai response complete\n" + "─" * 60)
                    else:
                        print(msg.get("content", ""), end="", flush=True)
                elif t == "error":
                    print(f"⚠  ERROR: {msg.get('message')}")
                else:
                    print(f"   {t}: {msg}")

            print("\n✓ Test window complete. Switching back to PTT…")
            await ws.send(json.dumps({"type": "set_voice_mode", "mode": "push_to_talk"}))

    except OSError as e:
        print(f"✗ Could not connect to {URL}: {e}", file=sys.stderr)
        print("  → Is the backend running?  cd backend && .venv/bin/python main.py",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
