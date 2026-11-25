"""POST /api/chat — run one LYRA turn (AI reply, or planned tool execution)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_services, rate_limit
from app.core.errors import ok
from app.schemas import ChatRequest

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> dict:
    rate_limit(request, "chat")
    services = get_services(request)
    result = await services.chat.run_turn(body.message, body.session_id)
    return {"success": True, **result, "data": result, "message": "Request completed"}
