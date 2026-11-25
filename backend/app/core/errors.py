"""Standard response envelope and error handling for the LYRA API.

Success:  {"success": true,  "data": ..., "message": "..."}
Failure:  {"success": false, "error": {"code": "...", "message": "..."}}

Internal exception details are logged server-side and never returned to clients.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from lyra.core.exceptions import (
    MemoryNotFoundError,
    MemoryPolicyViolationError,
    ModelValidationError,
    NoAvailableProviderError,
    ProviderError,
)
from lyra.observability.logging import get_logger, sanitize_text

logger = get_logger("api.errors")


class APIError(Exception):
    """An error that is safe to show to API clients."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def ok(data: Any = None, message: str = "Request completed") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message}}


def _json_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message))


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return _json_error(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path"))
        msg = first.get("msg", "Invalid request")
        return _json_error(422, "VALIDATION_ERROR", f"{loc}: {msg}" if loc else msg)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        detail = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").title()
        return _json_error(exc.status_code, code, detail)

    @app.exception_handler(MemoryPolicyViolationError)
    async def _memory_policy(_: Request, exc: MemoryPolicyViolationError) -> JSONResponse:
        return _json_error(422, "MEMORY_REJECTED", sanitize_text(str(exc)))

    @app.exception_handler(MemoryNotFoundError)
    async def _memory_missing(_: Request, exc: MemoryNotFoundError) -> JSONResponse:
        return _json_error(404, "NOT_FOUND", "Memory not found.")

    @app.exception_handler(ModelValidationError)
    async def _model_validation(_: Request, exc: ModelValidationError) -> JSONResponse:
        return _json_error(422, "VALIDATION_ERROR", sanitize_text(str(exc)))

    @app.exception_handler(NoAvailableProviderError)
    async def _no_provider(_: Request, exc: NoAvailableProviderError) -> JSONResponse:
        logger.warning("No AI provider available: %s", sanitize_text(str(exc)))
        return _json_error(503, "PROVIDER_UNAVAILABLE", "AI provider is currently unavailable.")

    @app.exception_handler(ProviderError)
    async def _provider(_: Request, exc: ProviderError) -> JSONResponse:
        logger.warning("Provider error: %s", sanitize_text(str(exc)))
        return _json_error(502, "PROVIDER_ERROR", "The AI service returned an error. Please try again.")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled API error: %s: %s", type(exc).__name__, sanitize_text(str(exc)))
        return _json_error(500, "INTERNAL_ERROR", "An unexpected error occurred.")
