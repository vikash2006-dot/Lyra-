"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.services.container import AppServices


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def rate_limit(request: Request, bucket: str) -> None:
    services: AppServices = request.app.state.services
    client = request.client.host if request.client else "local"
    services.limiter.check(f"{client}:{bucket}")
