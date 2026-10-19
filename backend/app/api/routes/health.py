from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import get_container
from app.core.container import AppContainer
from app.schemas.system import ComponentStatus, HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and dependency status")
async def health(c: AppContainer = Depends(get_container)) -> HealthResponse:
    components = await c.component_status()
    degraded = any(s.status in {"down", "degraded"} for s in components.values())
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=__version__,
        environment=c.settings.environment,
        components=components,
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="Readiness: can the API serve RAG requests?",
    responses={503: {"model": ReadyResponse}},
)
async def ready(c: AppContainer = Depends(get_container)) -> JSONResponse:
    components = await c.component_status()
    checks: dict[str, ComponentStatus] = {
        "qdrant": components["qdrant"],
        "bm25_index": ComponentStatus(
            status="ok" if c.bm25.loaded else "down",
            detail=None if c.bm25.loaded else "Lexical index not built",
        ),
        "openai": components["openai"],
    }
    is_ready = all(s.status == "ok" for s in checks.values())
    body = ReadyResponse(ready=is_ready, checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if is_ready else 503)
