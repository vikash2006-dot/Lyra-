"""Persistent memory CRUD + search, backed by LYRA's MemoryManager (policy enforced)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from lyra.models.memory import MemoryRecord, MemoryType

from app.api.deps import get_services
from app.core.errors import APIError, ok
from app.schemas import MemoryCreateRequest, MemoryUpdateRequest

router = APIRouter(tags=["memory"])


def _public(record: MemoryRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "type": record.type.value,
        "content": record.content,
        "source": record.source,
        "importance": record.importance,
        "confidence": record.confidence,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }


@router.get("/memory/types")
async def memory_types() -> dict:
    return ok([t.value for t in MemoryType])


@router.get("/memory")
async def list_memory(
    request: Request,
    q: str | None = Query(None, max_length=200),
    type: str | None = Query(None, max_length=40),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    services = get_services(request)
    mm = services.runtime.memory_manager
    if q and q.strip():
        records = mm.search(services.user_id, q.strip(), memory_type=type or None, limit=limit)
    else:
        records = mm.list_memories(services.user_id, memory_type=type or None, limit=limit)
    return ok([_public(r) for r in records])


@router.post("/memory", status_code=201)
async def create_memory(body: MemoryCreateRequest, request: Request) -> dict:
    services = get_services(request)
    record = services.runtime.memory_manager.remember(
        user_id=services.user_id,
        content=body.content,
        memory_type=body.type,
        source="user_ui",
        importance=body.importance,
        confidence=body.confidence,
    )
    return ok(_public(record), "Memory saved")


@router.get("/memory/{memory_id}")
async def get_memory(memory_id: str, request: Request) -> dict:
    services = get_services(request)
    record = services.runtime.memory_manager.recall(memory_id, services.user_id)
    if record is None:
        raise APIError("NOT_FOUND", "Memory not found.", 404)
    return ok(_public(record))


@router.put("/memory/{memory_id}")
async def update_memory(memory_id: str, body: MemoryUpdateRequest, request: Request) -> dict:
    services = get_services(request)
    record = services.runtime.memory_manager.modify(
        memory_id=memory_id,
        user_id=services.user_id,
        content=body.content,
        memory_type=body.type,
        importance=body.importance,
        confidence=body.confidence,
    )
    return ok(_public(record), "Memory updated")


@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str, request: Request) -> dict:
    services = get_services(request)
    if not services.runtime.memory_manager.forget(memory_id, services.user_id):
        raise APIError("NOT_FOUND", "Memory not found.", 404)
    return ok({"id": memory_id}, "Memory deleted")
