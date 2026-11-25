"""GET /api/health — real readiness of the backend and its core services."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from app.core.errors import ok

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    services = getattr(request.app.state, "services", None)
    if services is None:
        return ok({"status": "starting", "services": {}}, "Backend is starting")
    rt = services.runtime
    configured = [p.name for p in rt.router.list_providers() if p.is_configured]
    checks = {
        "orchestrator": rt.orchestrator is not None,
        "ai_providers": bool(configured),
        "tools": len(rt.tool_registry.list_tools()) > 0 if hasattr(rt.tool_registry, "list_tools") else True,
        "memory": _probe(lambda: rt.memory_manager.list_memories(services.user_id, limit=1)),
        "learning": _probe(lambda: rt.learning_service.repository.list_skills()),
        "api_store": services.store.ping(),
        "voice_stt": bool(services.voice.status()["stt_ready"]),
        "voice_tts": bool(services.voice.status()["tts_ready"]),
        "scheduler": services.scheduler_running,
    }
    core_ok = checks["orchestrator"] and checks["memory"] and checks["api_store"]
    status = "ok" if core_ok and checks["ai_providers"] else ("degraded" if core_ok else "error")
    return ok(
        {
            "status": status,
            "services": checks,
            "configured_providers": configured,
            "offline_mode": rt.orchestrator.offline_mode,
            "uptime_seconds": round(time.time() - services.started_at, 1),
            "version": request.app.version,
        },
        "Backend is healthy" if status == "ok" else f"Backend is {status}",
    )


def _probe(fn) -> bool:
    try:
        fn()
        return True
    except Exception:
        return False
