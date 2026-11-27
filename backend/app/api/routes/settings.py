"""Settings: safe, read-only configuration view plus runtime-adjustable options.

API keys are never returned — only whether each provider is configured.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_services
from app.core.errors import ok
from app.schemas import SettingsUpdateRequest
from app.services.container import AppServices, apply_preferences, assistant_preferences, provider_summaries

router = APIRouter(tags=["settings"])


def _settings_view(services: AppServices) -> dict:
    s = services.runtime.settings
    return {
        "general": {
            "environment": s.lyra_env,
            "log_level": s.log_level,
            "offline_mode": services.runtime.orchestrator.offline_mode,
            "request_timeout_seconds": s.request_timeout_seconds,
        },
        "providers": {
            "priority": list(s.provider_priority),
            "rate_limit_cooldown_seconds": s.rate_limit_cooldown_seconds,
            "local_provider_enabled": s.local_provider_enabled,
            "local_model_name": s.local_model_name,
        },
        "voice": {
            "stt_provider": s.stt_provider,
            "tts_provider": s.tts_provider,
            "elevenlabs_configured": bool(s.elevenlabs_api_key),
            "voice_timeout_seconds": s.voice_timeout_seconds,
            "silence_duration_seconds": s.voice_silence_duration_seconds,
        },
        "computer": {
            "require_confirmation": s.computer_require_confirmation,
            "allowed_apps": list(s.computer_allow_apps),
            "blocked_apps": list(s.computer_blocked_apps),
        },
        "browser": {
            "headless": s.browser_headless,
            "driver": s.browser_driver_type,
            "blocked_domains": list(s.browser_blocked_domains),
        },
        "integrations": {
            "anakin_configured": bool(s.anakin_api_key and s.anakin_app_id),
            "anakin_workflows": len(s.anakin_workflows),
            "tavily_configured": bool(s.tavily_api_key),
        },
        "server": {
            "token_required": bool(services.config.api_token),
            "cors_origins": list(services.config.cors_origins),
            "max_upload_mb": services.config.max_upload_bytes // (1024 * 1024),
        },
        "assistant": assistant_preferences(services),
        "editable": [
            "general.offline_mode",
            "assistant.emotional_awareness",
            "assistant.audio_event_detection",
            "assistant.cough_detection",
            "assistant.voice",
            "assistant.speech_rate",
        ],
        "note": "Other values come from backend/.env; edit it and restart the backend to change them.",
    }


@router.get("/settings")
async def get_settings(request: Request) -> dict:
    return ok(_settings_view(get_services(request)))


@router.put("/settings")
async def update_settings(body: SettingsUpdateRequest, request: Request) -> dict:
    services = get_services(request)
    if body.offline_mode is not None:
        # The orchestrator's setter propagates to the router, routing strategy and tool executor.
        services.runtime.orchestrator.offline_mode = body.offline_mode
    apply_preferences(services, body.model_dump(exclude_unset=True, exclude={"offline_mode"}))
    return ok(_settings_view(services), "Settings updated")


@router.get("/settings/providers")
async def providers(request: Request) -> dict:
    services = get_services(request)
    status = services.runtime.router.get_runtime_status()
    return ok({
        "current_provider": status.get("current_provider"),
        "available": status.get("available_providers", []),
        "providers": provider_summaries(services.runtime),
    })
