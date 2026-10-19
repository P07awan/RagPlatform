"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload --port 8000
Swagger UI:   http://localhost:8000/docs     ReDoc: http://localhost:8000/redoc
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app import __version__
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.container import AppContainer
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.timing import TimingMiddleware

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, container: AppContainer | None = None) -> FastAPI:
    if settings is None:
        try:
            settings = get_settings()
        except ValidationError as exc:
            # Fail fast with a readable message instead of a long pydantic traceback.
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'settings'}: {e['msg']}"
                for e in exc.errors()
            )
            raise SystemExit(f"Invalid configuration: {problems}") from None
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        c = container or AppContainer(settings)
        app.state.container = c
        await c.startup()
        logger.info(
            "application started",
            extra={"environment": settings.environment, "version": __version__},
        )
        try:
            yield
        finally:
            await c.shutdown()
            logger.info("application stopped")

    is_prod = settings.environment == "production"
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Retrieval-Augmented Generation API: document ingestion, hybrid retrieval "
            "(dense + BM25 + RRF), cross-encoder reranking, grounded answers with citations, "
            "SSE streaming and RAGAS evaluation. Protected endpoints require `X-API-Key`."
        ),
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    register_exception_handlers(app)

    # Middleware order: last added runs first. Request ID must wrap everything.
    app.add_middleware(TimingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # API key header, no cookies
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID", "Accept"],
        expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
        max_age=600,
    )
    app.add_middleware(RequestIDMiddleware)
    app.include_router(api_router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "docs": "/docs", "api": API_PREFIX}

    if is_prod:
        logger.info("production mode: stack traces are never returned to clients")
    return app


app = create_app()
