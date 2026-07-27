"""
AI Mentor — Python backend entry point.
"""

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from api.ws_handler import handle_connection, set_shared_state
from modules.ai_router import ollama_client
from modules.ai_router.router import AIRouter
from modules.screen_capture import ScreenCaptureEngine, ScreenContext
from modules.voice_engine import VoicePipeline, VoiceMode
from modules.react_planner import ConversationOrchestrator
from modules.role_manager import RoleManager, Role
from modules.memory_manager import MemoryManager, Memory, MemoryKind
from modules.overlay_engine import OverlayEngine
from modules.proactive_engine import ProactiveMonitor, TriggerEvent
from modules.agent_tools import ToolRegistry
from modules.agent_tools.builtins import (
    SearchMemoryTool, SaveMemoryTool, RecallConversationTool, GetScreenContextTool,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mentor.main")

_router       = AIRouter()
_capture      = ScreenCaptureEngine(interval_seconds=2.0)
_voice        = VoicePipeline(
    mode=VoiceMode.PUSH_TO_TALK,
    whisper_model="small.en",   # better STT quality than base; ~480MB
    tts_provider="kokoro",
    tts_voice="af_heart",
)
_memory       = MemoryManager()
_tools        = ToolRegistry()
_orchestrator = ConversationOrchestrator(_router, memory=_memory, tools=_tools)
_roles        = RoleManager()

# Register the Tier-1 tool kit. Each tool gets the dependency it needs.
_tools.register(SearchMemoryTool(_memory))
_tools.register(SaveMemoryTool(_memory))
_tools.register(RecallConversationTool(_memory, lambda: _orchestrator.session_id))
_tools.register(GetScreenContextTool(_capture))
_overlay      = OverlayEngine()
_proactive    = ProactiveMonitor(proactivity=_orchestrator.proactivity)


_last_watching_emit_at: float = 0.0


async def _on_screen_context(ctx: ScreenContext) -> None:
    _router.update_screen_context(ctx.to_prompt_block())

    # Throttle watching heartbeat to ~one every 4s, just enough for the UI
    # to confirm the eye is open without flooding the WS.
    import time as _t
    global _last_watching_emit_at
    if _t.time() - _last_watching_emit_at >= 4.0:
        _last_watching_emit_at = _t.time()
        from api.ws_handler import _broadcast
        try:
            await _broadcast({
                "type": "watching",
                "app": ctx.active_app.name if ctx.active_app else None,
                "content_type": ctx.content_type.value,
                "file": ctx.file_path,
                "is_blank": ctx.is_blank,
                "text_len": len(ctx.masked_text or ""),
            })
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # ── Provider availability snapshot ────────────────────────────────────────
    ok = await ollama_client.health_check(settings.ollama_base_url)
    if ok:
        models = await ollama_client.list_models(settings.ollama_base_url)
        logger.info("✓ Ollama available. Models: %s", models)
    else:
        logger.warning("✗ Ollama NOT available — start with `ollama serve`")

    if settings.openai_api_key:
        logger.info("✓ OpenAI configured (model=%s, key=sk-…%s)",
                    settings.openai_default_model, settings.openai_api_key[-4:])
    else:
        logger.info("○ OpenAI not configured (set OPENAI_API_KEY in backend/.env)")

    if settings.anthropic_api_key:
        logger.info("✓ Anthropic configured (model=%s, key=sk-ant-…%s)",
                    settings.anthropic_default_model, settings.anthropic_api_key[-4:])
    else:
        logger.info("○ Anthropic not configured (set ANTHROPIC_API_KEY in backend/.env)")

    logger.info("→ Active providers: %s", _router.get_available_providers())

    # Apply the active role (defaults to "default" — see RoleManager)
    role = _roles.active
    _orchestrator.apply_role(role)
    _voice.get_tts_engine().set_voice(role.voice)
    logger.info("→ Active role: %s %s (%s)", role.emoji, role.name, role.id)

    set_shared_state(router=_router, orchestrator=_orchestrator,
                     voice=_voice, capture=_capture, roles=_roles,
                     memory=_memory, overlay=_overlay, proactive=_proactive)

    _capture.add_listener(_on_screen_context)

    # Wire proactive monitor: trigger → orchestrator.proactive_speak → broadcast
    from api.ws_handler import broadcast_proactive
    async def _on_proactive_trigger(evt: TriggerEvent) -> None:
        try:
            await broadcast_proactive(_orchestrator, evt)
        except Exception:
            logger.exception("[proactive] dispatch failed")

    _proactive.on_trigger(_on_proactive_trigger)
    _proactive.set_proactivity(_orchestrator.proactivity)
    _proactive.attach(_capture)
    logger.info("→ Proactive monitor attached (level=%d)", _proactive.level)

    _capture.start()
    logger.info("Screen capture started")

    await _voice.start()
    logger.info("Voice pipeline started (mode=%s)", _voice.mode.value)

    yield

    _voice.stop()
    _capture.stop()
    logger.info("Backend shut down")


app = FastAPI(title="AI Mentor Backend", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/agent/tools")
async def list_agent_tools():
    return {
        "tools": [
            {"name": t.name, "description": t.description,
             "parameters": t.parameters_schema}
            for t in _tools.definitions()
        ],
    }


@app.post("/proactive/snooze")
async def snooze_proactive(payload: dict):
    seconds = int(payload.get("seconds", 600))
    _proactive.snooze(seconds)
    return {"snoozed_for": seconds}


@app.post("/proactive/agent_mode")
async def set_agent_mode(payload: dict):
    enabled = bool(payload.get("enabled", False))
    _proactive.set_agent_mode(enabled)
    return {"agent_mode": _proactive.agent_mode}


@app.get("/proactive/status")
async def proactive_status():
    return {
        "level": _proactive.level,
        "is_snoozed": _proactive.is_snoozed(),
        "agent_mode": _proactive.agent_mode,
    }


@app.get("/health")
async def health():
    settings = get_settings()
    ollama_ok = await ollama_client.health_check(settings.ollama_base_url)
    return {
        "status": "ok",
        "ollama": ollama_ok,
        "capture_paused": _capture.is_paused,
        "voice_mode": _voice.mode.value,
        "voice_state": _voice.state.value,
        "conversation_mode": _orchestrator.mode.value,
        "proactivity": _orchestrator.proactivity,
        "providers": _router.get_available_providers(),
        "preferred_provider": _router.preferred_provider,
    }


@app.get("/providers")
async def list_providers():
    s = get_settings()
    return {
        "available": _router.get_available_providers(),
        "preferred": _router.preferred_provider,
        "diagnostics": {
            "ollama":    {"configured": True,
                           "model": s.ollama_default_model,
                           "url": s.ollama_base_url},
            "openai":    {"configured": bool(s.openai_api_key),
                           "model": s.openai_default_model,
                           "reason": None if s.openai_api_key
                                     else "OPENAI_API_KEY not set in backend/.env"},
            "anthropic": {"configured": bool(s.anthropic_api_key),
                           "model": s.anthropic_default_model,
                           "reason": None if s.anthropic_api_key
                                     else "ANTHROPIC_API_KEY not set in backend/.env"},
        },
    }


@app.post("/capture/pause")
async def pause_capture():
    _capture.pause()
    return {"capture": "paused"}


@app.post("/capture/resume")
async def resume_capture():
    _capture.resume()
    return {"capture": "resumed"}


@app.get("/capture/context")
async def get_screen_context():
    ctx = _capture.last_context
    if ctx is None:
        return {"context": None}
    return {
        "app": ctx.active_app.name if ctx.active_app else None,
        "content_type": ctx.content_type.value,
        "is_blank": ctx.is_blank,
        "text_length": len(ctx.masked_text),
        "errors": ctx.error_messages,
        "urls": ctx.urls,
    }


@app.post("/overlay/annotate")
async def overlay_annotate(payload: dict):
    """
    Forward an annotation to all WS clients (the Tauri frontend listens and
    invokes the overlay command on its end). Body is a single annotation or
    a list under {"annotations": [...]}.
    """
    from modules.overlay_engine.models import (
        HighlightAnnotation, CircleAnnotation,
        ArrowAnnotation, LabelAnnotation,
    )
    items_raw = payload.get("annotations") or [payload]
    parsed = []
    for raw in items_raw:
        kind = raw.get("kind")
        try:
            if kind == "highlight": parsed.append(HighlightAnnotation(**raw))
            elif kind == "circle":  parsed.append(CircleAnnotation(**raw))
            elif kind == "arrow":   parsed.append(ArrowAnnotation(**raw))
            elif kind == "label":   parsed.append(LabelAnnotation(**raw))
            else: continue
        except Exception as exc:
            return {"error": f"invalid annotation: {exc}"}

    await _overlay.annotate(parsed)
    return {"annotated": [a.id for a in parsed]}


@app.post("/overlay/clear")
async def overlay_clear():
    await _overlay.clear()
    return {"cleared": True}


@app.get("/memories")
async def get_memories(enabled_only: bool = False):
    return {
        "extraction_enabled": _memory.extraction_enabled,
        "memories": [m.model_dump(mode="json") for m in _memory.list_memories(enabled_only=enabled_only)],
    }


@app.post("/memories")
async def create_memory(payload: dict):
    content = (payload.get("content") or "").strip()
    if not content:
        return {"error": "content required"}
    try:
        kind = MemoryKind(payload.get("kind", "note"))
    except ValueError:
        kind = MemoryKind.NOTE
    m = _memory.add_memory(content=content, kind=kind,
                            role_id=payload.get("role_id"))
    return m.model_dump(mode="json")


@app.patch("/memories/{memory_id}")
async def patch_memory(memory_id: str, payload: dict):
    kind = None
    if "kind" in payload:
        try:
            kind = MemoryKind(payload["kind"])
        except ValueError:
            return {"error": f"invalid kind: {payload['kind']}"}
    m = _memory.update_memory(
        memory_id,
        content=payload.get("content"),
        kind=kind,
        enabled=payload.get("enabled"),
    )
    if not m:
        return {"error": "not found"}
    return m.model_dump(mode="json")


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str):
    return {"deleted": _memory.delete_memory(memory_id)}


@app.post("/memories/clear-all")
async def clear_all_memories():
    n = _memory.clear_all()
    return {"deleted": n}


@app.post("/memories/extraction")
async def set_extraction(payload: dict):
    enabled = bool(payload.get("enabled", True))
    _memory.set_extraction_enabled(enabled)
    return {"extraction_enabled": enabled}


@app.get("/roles")
async def get_roles():
    return {
        "active": _roles.active_id,
        "roles": [r.model_dump() for r in _roles.list_roles()],
    }


@app.post("/roles/{role_id}/activate")
async def activate_role(role_id: str):
    try:
        role = _roles.set_active(role_id)
    except KeyError:
        return {"error": f"Role not found: {role_id}"}
    _orchestrator.apply_role(role)
    _voice.get_tts_engine().set_voice(role.voice)
    return {"active": role.id, "name": role.name}


@app.post("/roles")
async def create_or_update_role(role: Role):
    saved = _roles.upsert(role)
    return saved.model_dump()


@app.delete("/roles/{role_id}")
async def delete_role(role_id: str):
    try:
        ok = _roles.delete(role_id)
    except ValueError as e:
        return {"error": str(e)}
    return {"deleted": ok}


@app.get("/voice/devices")
async def get_input_devices():
    """List every input device with detected kind + RMS probe + ranking score.

    Lets you confirm which mic the engine picked. Restart backend to apply.
    """
    from modules.voice_engine.audio_capture import list_input_devices
    devices = list_input_devices()
    devices.sort(key=lambda d: d["score"], reverse=True)
    return {"devices": devices}


@app.get("/voice/voices")
async def list_voices():
    tts = _voice.get_tts_engine()
    return {
        "backend": tts.backend_name,
        "current": tts.voice,
        "voices": tts.list_voices(),
    }


@app.post("/voice/set")
async def set_voice(payload: dict):
    voice = payload.get("voice")
    if not voice:
        return {"error": "missing 'voice'"}
    _voice.get_tts_engine().set_voice(voice)
    return {"voice": voice}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await handle_connection(ws)


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
