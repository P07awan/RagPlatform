"""Application exceptions and consistent JSON error responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base error with a client-safe message and machine-readable code."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigurationError(AppError):
    status_code = 503
    code = "not_configured"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UpstreamError(AppError):
    """An external dependency (OpenAI, Qdrant, ...) failed."""

    status_code = 502
    code = "upstream_error"


class UpstreamAuthError(UpstreamError):
    code = "upstream_auth_error"


class UpstreamQuotaError(UpstreamError):
    status_code = 503
    code = "upstream_quota_exceeded"


class UpstreamRateLimited(UpstreamError):
    status_code = 503
    code = "upstream_rate_limited"


class UpstreamTimeout(UpstreamError):
    status_code = 504
    code = "upstream_timeout"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


class VectorDimensionMismatch(AppError):
    status_code = 503
    code = "vector_dimension_mismatch"


class RerankerUnavailable(AppError):
    status_code = 503
    code = "reranker_unavailable"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


def error_body(code: str, message: str, details: object | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "error": {"code": code, "message": message, "request_id": request_id_ctx.get()}
    }
    if details is not None:
        body["error"]["details"] = details  # type: ignore[index]
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        log = logger.warning if exc.status_code < 500 else logger.error
        log("request failed", extra={"error_code": exc.code, "error": exc.message})
        return JSONResponse(error_body(exc.code, exc.message, exc.details), exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}
        return JSONResponse(
            error_body(code.get(exc.status_code, "http_error"), str(exc.detail)),
            exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(error_body("validation_error", "Invalid request", details), 422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(error_body("internal_error", "An unexpected error occurred"), 500)
