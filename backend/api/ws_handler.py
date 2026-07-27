"""
WebSocket handler — single persistent connection from the Tauri frontend.

Routes everything through the ConversationOrchestrator (Phase 4).
"""

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from models.messages import (
    ChunkMessage, ErrorMessage, PongMessage, StatusMessage,
    VoiceStateMessage, TranscriptMessage,
)
from modules.ai_router.router import AIRouter
from modules.react_planner import (
    ConversationOrchestrator, ConversationMode, PlannerDecision,
)
from modules.role_manager import RoleManager
from modules.memory_manager import MemoryManager, MemoryKind
from modules.overlay_engine import OverlayEngine
from modules.overlay_engine.models import Annotation
from modules.proactive_engine import ProactiveMonitor, TriggerEvent
from modules.screen_capture import ScreenCaptureEngine
from modules.voice_engine import VoicePipeline, VoiceMode
from modules.voice_engine.models import TranscriptResult, VoiceState

logger = logging.getLogger(__name__)


@dataclass
class SharedState:
    router: AIRouter
    orchestrator: ConversationOrchestrator
    voice: VoicePipeline
    capture: ScreenCaptureEngine
    roles: RoleManager
    memory: MemoryManager
    overlay: OverlayEngine
    proactive: ProactiveMonitor


_state: Optional[SharedState] = None


_active_sockets: list[WebSocket] = []


def set_shared_state(
    router: AIRouter,
    orchestrator: ConversationOrchestrator,
    voice: VoicePipeline,
    capture: ScreenCaptureEngine,
    roles: RoleManager,
    memory: MemoryManager,
    overlay: OverlayEngine,
    proactive: ProactiveMonitor,
) -> None:
    global _state
    _state = SharedState(router=router, orchestrator=orchestrator,
                         voice=voice, capture=capture, roles=roles,
                         memory=memory, overlay=overlay, proactive=proactive)

    # Wire overlay engine → broadcast to all WS clients
    async def _broadcast_annotate(items: list[Annotation]) -> None:
        msg = json.dumps({
            "type": "overlay_annotate",
            "annotations": [a.model_dump() for a in items],
        })
        for ws in list(_active_sockets):
            try:
                await ws.send_text(msg)
            except Exception:
                pass

    async def _broadcast_clear() -> None:
        msg = json.dumps({"type": "overlay_clear"})
        for ws in list(_active_sockets):
            try:
                await ws.send_text(msg)
            except Exception:
                pass

    overlay.on_annotate(_broadcast_annotate)
    overlay.on_clear(_broadcast_clear)


async def _send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        pass


async def _broadcast(payload: dict) -> None:
    """Send `payload` to every active WS client."""
    msg = json.dumps(payload)
    for ws in list(_active_sockets):
        try:
            await ws.send_text(msg)
        except Exception:
            pass


async def broadcast_proactive(
    orchestrator: ConversationOrchestrator,
    event: TriggerEvent,
) -> None:
    """
    Generate an AI-initiated coaching response for a trigger event and stream
    its chunks to every connected client. Called from the ProactiveMonitor.
    """
    response_id = str(uuid.uuid4())

    # Tell UI a proactive turn is starting
    await _broadcast({
        "type": "proactive_start",
        "id": response_id,
        "trigger": event.kind.value,
        "summary": event.summary,
    })
    await _broadcast(StatusMessage(state="thinking").model_dump())

    try:
        async for chunk in orchestrator.proactive_speak(event.summary):
            await _broadcast(ChunkMessage(
                id=response_id, content=chunk, done=False,
            ).model_dump())
        await _broadcast(ChunkMessage(
            id=response_id, content="", done=True,
        ).model_dump())
    except Exception as exc:
        logger.exception("[proactive] stream error")
        await _broadcast(ErrorMessage(message=str(exc)).model_dump())

    await _broadcast(StatusMessage(state="idle").model_dump())


async def handle_connection(ws: WebSocket) -> None:
    await ws.accept()
    conn_id = str(uuid.uuid4())[:8]
    logger.info("[ws:%s] connected", conn_id)

    if _state is None:
        await _send(ws, ErrorMessage(message="Backend not initialised").model_dump())
        await ws.close()
        return

    # Defensive: dedupe identical socket refs to avoid double-broadcast.
    if ws not in _active_sockets:
        _active_sockets.append(ws)

    # Voice wiring (one orchestrator instance shared across connections)
    async def _on_voice_transcript(result: TranscriptResult) -> None:
        await _send(ws, TranscriptMessage(text=result.text).model_dump())
        await _handle_chat(ws, result.text, model_override=None, is_voice=True)

    async def _on_voice_state(state: VoiceState) -> None:
        await _send(ws, VoiceStateMessage(
            state=state.value,
            mode=_state.voice.mode.value,
        ).model_dump())

    _state.voice.on_transcript(_on_voice_transcript)
    _state.voice.on_state_change(_on_voice_state)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, ErrorMessage(message="Invalid JSON").model_dump())
                continue

            await _route(ws, msg, conn_id)

    except WebSocketDisconnect:
        logger.info("[ws:%s] disconnected", conn_id)
    except Exception:
        logger.exception("[ws:%s] unexpected error", conn_id)
    finally:
        if ws in _active_sockets:
            _active_sockets.remove(ws)


async def _route(ws: WebSocket, msg: dict, conn_id: str) -> None:
    t = msg.get("type")

    if t == "ping":
        await _send(ws, PongMessage().model_dump())

    elif t == "chat":
        content = msg.get("content", "").strip()
        if content:
            await _handle_chat(
                ws, content,
                model_override=msg.get("model"),
                provider_override=msg.get("provider"),
                is_voice=False,
            )

    elif t == "set_role":
        role_id = msg.get("role_id")
        try:
            role = _state.roles.set_active(role_id)
        except KeyError:
            await _send(ws, ErrorMessage(message=f"Role not found: {role_id}").model_dump())
            return
        _state.orchestrator.apply_role(role)
        _state.voice.get_tts_engine().set_voice(role.voice)
        await _send(ws, {
            "type": "role",
            "id": role.id,
            "name": role.name,
            "emoji": role.emoji,
            "voice": role.voice,
            "mode": role.conversation_mode,
            "proactivity": role.proactivity,
        })

    elif t == "set_provider":
        # global preferred provider; null/empty = auto
        provider = msg.get("provider") or None
        try:
            _state.router.set_preferred_provider(provider)
            await _send(ws, {
                "type": "provider",
                "provider": provider,
                "available": _state.router.get_available_providers(),
            })
        except ValueError as e:
            await _send(ws, ErrorMessage(message=str(e)).model_dump())

    elif t == "interrupt":
        _state.orchestrator.interrupt()
        _state.voice.interrupt_speech()

    elif t == "set_conversation_mode":
        try:
            mode = ConversationMode(msg.get("mode", "direct"))
            _state.orchestrator.set_mode(mode)
            await _send(ws, {"type": "conversation_mode", "mode": mode.value})
        except ValueError:
            await _send(ws, ErrorMessage(message=f"Unknown mode: {msg.get('mode')}").model_dump())

    elif t == "set_proactivity":
        level = int(msg.get("level", 2))
        _state.orchestrator.set_proactivity(level)
        _state.proactive.set_proactivity(_state.orchestrator.proactivity)
        await _send(ws, {"type": "proactivity", "level": _state.orchestrator.proactivity})

    elif t == "proactive_snooze":
        seconds = int(msg.get("seconds", 600))
        _state.proactive.snooze(seconds)
        await _send(ws, {"type": "proactive_status",
                         "snoozed": True,
                         "seconds": seconds})

    elif t == "set_agent_mode":
        enabled = bool(msg.get("enabled", False))
        _state.proactive.set_agent_mode(enabled)
        await _send(ws, {"type": "agent_mode",
                         "enabled": _state.proactive.agent_mode})

    elif t == "ptt_start":
        _state.voice.ptt_start()

    elif t == "ptt_stop":
        _state.voice.ptt_stop()

    elif t == "set_tts_voice":
        voice = msg.get("voice")
        if voice:
            _state.voice.get_tts_engine().set_voice(voice)
            await _send(ws, {"type": "tts_voice", "voice": voice})

    elif t == "set_voice_mode":
        try:
            mode = VoiceMode(msg.get("mode", "off"))
            _state.voice.set_mode(mode)
            await _send(ws, VoiceStateMessage(
                state=_state.voice.state.value,
                mode=mode.value,
            ).model_dump())
        except ValueError:
            await _send(ws, ErrorMessage(message=f"Unknown voice mode: {msg.get('mode')}").model_dump())

    elif t == "capture_pause":
        _state.capture.pause()
        await _send(ws, {"type": "capture_status", "paused": True})

    elif t == "capture_resume":
        _state.capture.resume()
        await _send(ws, {"type": "capture_status", "paused": False})

    else:
        logger.warning("[ws:%s] unknown message type: %s", conn_id, t)


async def _handle_chat(
    ws: WebSocket,
    content: str,
    model_override: Optional[str] = None,
    provider_override: Optional[str] = None,
    is_voice: bool = False,
) -> None:
    """Shared chat handler — runs the orchestrator and streams chunks + TTS."""
    response_id = str(uuid.uuid4())

    # User is actively engaging — reset proactive cooldown/stuck-timer so we
    # don't immediately fire another nudge right after the user's message.
    if _state and _state.proactive:
        _state.proactive.reset_state()

    await _send(ws, StatusMessage(state="thinking").model_dump())

    tts_streamer = _state.voice.get_tts_streamer()

    async def emit_decision(decision: PlannerDecision) -> None:
        await _send(ws, {
            "type": "planner_decision",
            "action": decision.action.value,
            "reasoning": decision.reasoning,
        })

    try:
        async with tts_streamer as streamer:
            await _send(ws, StatusMessage(state="speaking").model_dump())

            # Agent-loop: streams text chunks AND structured tool_call /
            # tool_result events. We forward each one straight to the UI.
            async for evt in _state.orchestrator.run_agent_turn(
                user_message=content,
                is_voice=is_voice,
                model_override=model_override,
                provider_override=provider_override,
            ):
                etype = evt.get("type")
                if etype == "chunk":
                    # Use the agent-loop's response_id for stable threading
                    await _send(ws, evt)
                    if is_voice and evt.get("content"):
                        await streamer.push(evt["content"])
                else:
                    # tool_call / tool_result — pass through verbatim
                    await _send(ws, evt)

        # Stream end already signalled by the agent loop's final chunk(done=True),
        # but keep the explicit terminator for back-compat with old clients.
        await _send(ws, ChunkMessage(
            id=response_id, content="", done=True,
        ).model_dump())

    except Exception as exc:
        logger.exception("[ws] stream error")
        await _send(ws, ErrorMessage(message=str(exc)).model_dump())

    await _send(ws, StatusMessage(state="idle").model_dump())
