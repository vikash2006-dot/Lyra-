"""Screen awareness APIs: status, capture, analysis, visual commands, context and monitoring."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Query, Request

from lyra.vision.capture import ScreenCaptureError, ScreenPermissionError, optimize_for_vision
from lyra.vision.service import VisualActionError

from app.api.deps import get_services, rate_limit
from app.core.errors import APIError, ok
from app.schemas import (
    VisionAnalyzeRequest,
    VisionCaptureRequest,
    VisionCommandRequest,
    VisionMonitorRequest,
    VisionSettingsRequest,
)
from app.services.container import apply_preferences

router = APIRouter(prefix="/vision", tags=["vision"])


def _screen(request: Request):
    services = get_services(request)
    if services.runtime.screen is None:
        raise APIError("VISION_UNAVAILABLE", "Screen awareness is not available.", 503)
    return services, services.runtime.screen


def _map_errors(err: Exception) -> APIError:
    if isinstance(err, ScreenPermissionError):
        return APIError("SCREEN_PERMISSION_DENIED", str(err), 403)
    if isinstance(err, VisualActionError):
        return APIError("VISION_DISABLED", str(err), 409)
    return APIError("CAPTURE_FAILED", str(err) or "Screen capture failed.", 500)


@router.get("/status")
async def status(request: Request) -> dict:
    _, screen = _screen(request)
    return ok(screen.status())


@router.post("/permission/request")
async def request_permission(request: Request) -> dict:
    """Shows macOS's own Screen Recording prompt (explicit user action only)."""
    _, screen = _screen(request)
    return ok({"screen_permission": screen.capture_service.request_permission()},
              "If macOS showed a prompt, enable LYRA's host app, then restart the backend.")


@router.put("/settings")
async def update_settings(body: VisionSettingsRequest, request: Request) -> dict:
    services, screen = _screen(request)
    changes = {}
    if body.enabled is not None:
        changes["screen_awareness"] = body.enabled
    if body.cloud_consent is not None:
        changes["vision_cloud_consent"] = body.cloud_consent
    apply_preferences(services, changes)
    if body.enabled is False and screen.monitor.running:
        await screen.monitor.stop()
    return ok(screen.status(), "Screen awareness settings updated")


@router.post("/capture")
async def capture(body: VisionCaptureRequest, request: Request) -> dict:
    """Capture now and return a downscaled preview + local OCR/elements (no AI call)."""
    rate_limit(request, "vision")
    _, screen = _screen(request)
    try:
        ctx = await screen.observe(body.session_id, use_ai=False, target=body.target, display=body.display, fast_ocr=True)
    except (ScreenPermissionError, ScreenCaptureError, VisualActionError) as err:
        raise _map_errors(err) from err
    return ok({"context": ctx.to_dict(), "preview": await _preview(screen, body.session_id)}, "Screen captured")


@router.post("/analyze")
async def analyze(body: VisionAnalyzeRequest, request: Request) -> dict:
    rate_limit(request, "vision")
    _, screen = _screen(request)
    try:
        ctx = await screen.observe(body.session_id, question=body.question, use_ai=body.use_ai,
                                   target=body.target, display=body.display)
    except (ScreenPermissionError, ScreenCaptureError, VisualActionError) as err:
        raise _map_errors(err) from err
    return ok({"context": ctx.to_dict(), "preview": await _preview(screen, body.session_id)}, "Screen analyzed")


@router.post("/ask")
async def ask(body: VisionCommandRequest, request: Request) -> dict:
    """Ask about / act on the screen in natural language (runs as a normal, tracked LYRA turn)."""
    rate_limit(request, "chat")
    services, screen = _screen(request)
    result = await services.chat.run_turn(body.command, body.session_id, source="vision")
    ctx = screen.context(result["session_id"])
    return ok({**result, "context": ctx.to_dict() if ctx else None})


@router.get("/context")
async def get_context(request: Request, session_id: str | None = Query(None)) -> dict:
    _, screen = _screen(request)
    ctx = screen.context(session_id)
    return ok({"context": ctx.to_dict() if ctx else None, "preview": await _preview(screen, session_id) if ctx else None})


@router.delete("/context")
async def clear_context(request: Request, session_id: str | None = Query(None)) -> dict:
    _, screen = _screen(request)
    screen.clear_context(session_id)
    return ok({"cleared": True}, "Visual context cleared")


@router.post("/monitor/start")
async def monitor_start(request: Request, body: VisionMonitorRequest | None = None) -> dict:
    _, screen = _screen(request)
    if not screen.enabled:
        raise APIError("VISION_DISABLED", "Turn on screen awareness first.", 409)
    return ok(screen.monitor.start(body.interval_seconds if body else None), "Screen monitoring started")


@router.post("/monitor/stop")
async def monitor_stop(request: Request) -> dict:
    _, screen = _screen(request)
    return ok(await screen.monitor.stop(), "Screen monitoring stopped")


@router.get("/monitor/status")
async def monitor_status(request: Request) -> dict:
    _, screen = _screen(request)
    return ok(screen.monitor.status())


async def _preview(screen, session_id: str | None) -> dict | None:
    png = screen.latest_screenshot_png(session_id)
    if not png:
        return None
    data, mime, _ = await optimize_for_vision(png, max_side=960, quality=70)
    return {"mime_type": mime, "data_base64": base64.b64encode(data).decode("ascii")}
