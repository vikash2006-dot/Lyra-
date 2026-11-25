"""System status: providers, tools, voice, storage and runtime information."""

from __future__ import annotations

import platform
import sys
import time

from fastapi import APIRouter, Request

from app.api.deps import get_services
from app.core.errors import ok
from app.services.container import provider_summaries

router = APIRouter(tags=["system"])


@router.get("/system/status")
async def system_status(request: Request) -> dict:
    services = get_services(request)
    rt = services.runtime
    runtime_status = rt.router.get_runtime_status()
    tools = [
        {
            "name": t.name,
            "description": t.description,
            "permission": t.permission_level.value,
            "requires_network": bool(getattr(t, "requires_network", False)),
        }
        for t in rt.tool_registry.list_tools()
    ]
    try:
        memory_count = len(rt.memory_manager.list_memories(services.user_id, limit=1000))
    except Exception:
        memory_count = None
    return ok({
        "backend": {
            "uptime_seconds": round(time.time() - services.started_at, 1),
            "python": sys.version.split()[0],
            "platform": f"{platform.system()} {platform.release()}",
            "environment": services.config.app_env,
            "init_errors": services.init_errors,
        },
        "ai": {
            "current_provider": runtime_status.get("current_provider"),
            "available_providers": runtime_status.get("available_providers", []),
            "offline_mode": rt.orchestrator.offline_mode,
            "providers": provider_summaries(rt),
        },
        "tools": tools,
        "voice": services.voice.status(),
        "computer": {
            "platform_supported": sys.platform == "darwin",
            "controller_enabled": bool(getattr(rt.computer_controller, "enabled", False)),
        },
        "automation": {"scheduler_running": services.scheduler_running},
        "storage": {**services.store.counts(), "memories": memory_count},
        "tasks": {"active": services.tasks.active_count},
        "realtime": {"event_subscribers": services.bus.subscriber_count},
    })
