"""FastAPI application factory for the LYRA backend."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from lyra.observability.logging import get_logger, setup_logging

from app.core.config import BACKEND_DIR, PROJECT_ROOT, ServerConfig, load_server_config
from app.core.errors import install_error_handlers
from app.core.migration import migrate_legacy_data
from app.core.security import check_http_token
from app.services.container import AppServices, RuntimeFactory, build_services

logger = get_logger("api")


def create_app(
    config: ServerConfig | None = None,
    runtime_factory: RuntimeFactory | None = None,
    start_scheduler: bool = True,
) -> FastAPI:
    config = config or load_server_config()

    if config.is_production and not config.api_token:
        # A public server without a token would let anyone spend your AI quota and read your data.
        raise RuntimeError("LYRA_API_TOKEN must be set when APP_ENV=production.")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        if config.auto_migrate:
            report = migrate_legacy_data(PROJECT_ROOT, BACKEND_DIR, config.data_dir)
            if report.migrated or report.failed:
                logger.info("Data migration: migrated=%s failed=%s backup=%s",
                            report.migrated, report.failed, report.backup_dir)
        services = build_services(config, runtime_factory)
        app.state.services = services
        if start_scheduler:
            try:
                await services.runtime.scheduler.start()
                services.scheduler_running = True
            except Exception as err:  # automation is optional; never block startup
                services.init_errors.append(f"scheduler: {err}")
                logger.warning("Automation scheduler failed to start: %s", err)
        if services.runtime.screen is not None:
            from lyra.vision.ocr import warm_up

            app.state.ocr_warmup = asyncio.create_task(warm_up())  # background; never delays startup
        logger.info("LYRA API ready (env=%s, data=%s)", config.app_env, config.data_dir)
        try:
            yield
        finally:
            screen = services.runtime.screen
            if screen is not None and screen.monitor.running:
                await screen.monitor.stop()
            if services.scheduler_running:
                try:
                    await asyncio.wait_for(services.runtime.scheduler.stop(), timeout=5)
                except Exception:
                    pass
            try:
                await services.runtime.browser_manager.close()
            except Exception:
                pass

    async def require_token(request: Request) -> None:
        check_http_token(request, config.api_token)

    app = FastAPI(
        title="LYRA API",
        version="1.0.0",
        description="Backend API for LYRA — Personal AI Operating System.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    install_error_handlers(app)

    from app.api.routes import (
        chat,
        documents,
        health,
        learning,
        memory,
        sessions,
        settings,
        system,
        tasks,
        vision,
        voice,
    )
    from app.api.websocket import chat as ws_chat
    from app.api.websocket import events as ws_events
    from app.api.websocket import voice as ws_voice

    app.include_router(health.router, prefix="/api")  # health stays public for launchers/monitors
    protected = [Depends(require_token)]
    for module in (chat, tasks, voice, memory, sessions, settings, system, documents, learning, vision):
        app.include_router(module.router, prefix="/api", dependencies=protected)
    app.include_router(ws_chat.router)
    app.include_router(ws_voice.router)
    app.include_router(ws_events.router)
    return app


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def configure_logging() -> None:
    from lyra.config.settings import load_settings

    try:
        setup_logging(log_level=load_settings().log_level)
    except Exception:
        setup_logging(log_level="INFO")
