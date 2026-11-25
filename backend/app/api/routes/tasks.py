"""Task execution APIs: submit a command, track progress, view results, cancel."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from lyra.observability.logging import get_logger

from app.api.deps import get_services, rate_limit
from app.core.errors import APIError, ok
from app.schemas import TaskCreateRequest

router = APIRouter(tags=["tasks"])
logger = get_logger("api.tasks.routes")
_background: set[asyncio.Task] = set()


@router.post("/tasks", status_code=202)
async def create_task(body: TaskCreateRequest, request: Request) -> dict:
    rate_limit(request, "chat")
    services = get_services(request)
    command = services.chat.validate_message(body.command)
    session = services.sessions.resolve(body.session_id)
    if services.sessions.lock_for(session.session_id).locked():
        raise APIError("SESSION_BUSY", "LYRA is still working on the previous request in this chat.", 409)
    task = services.tasks.new_task(session.session_id, command, status="pending")

    async def _run() -> None:
        try:
            await services.chat.run_turn(command, session.session_id, task=task, source="task")
        except APIError as err:
            services.tasks.update(task, status="failed", error=err.message, message=err.message)
        except Exception:
            logger.exception("Background task %s crashed", task["id"])
            services.tasks.update(task, status="failed", error="The task failed unexpectedly.")

    handle = asyncio.create_task(_run())
    _background.add(handle)
    handle.add_done_callback(_background.discard)
    return ok(services.tasks.public(task), "Task accepted")


@router.get("/tasks")
async def list_tasks(request: Request, status: str | None = Query(None), limit: int = Query(50, ge=1, le=200)) -> dict:
    return ok(get_services(request).tasks.list(status=status, limit=limit))


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    return ok(get_services(request).tasks.get(task_id))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict:
    task = get_services(request).tasks.cancel(task_id)
    return ok(task, "Task cancelled")
