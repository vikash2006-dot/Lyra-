"""Conversation sessions and chat history."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.deps import get_services
from app.core.errors import ok
from app.schemas import SessionCreateRequest, SessionUpdateRequest

router = APIRouter(tags=["sessions"])


@router.post("/sessions", status_code=201)
async def create_session(request: Request, body: SessionCreateRequest | None = None) -> dict:
    return ok(get_services(request).sessions.create(body.title if body else None), "Session created")


@router.get("/sessions")
async def list_sessions(request: Request) -> dict:
    return ok(get_services(request).sessions.list())


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> dict:
    return ok(get_services(request).sessions.get_record(session_id))


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, body: SessionUpdateRequest, request: Request) -> dict:
    return ok(get_services(request).sessions.rename(session_id, body.title), "Session renamed")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict:
    get_services(request).sessions.delete(session_id)
    return ok({"id": session_id}, "Session deleted")


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, request: Request, limit: int | None = Query(None, ge=1, le=1000)) -> dict:
    return ok(get_services(request).sessions.messages(session_id, limit=limit))
