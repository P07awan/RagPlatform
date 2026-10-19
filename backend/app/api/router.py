from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.routes import chat, documents, evaluation, health, ingestion, retrieval, system
from app.core.security import verify_api_key

api_router = APIRouter()

# Health endpoints are deliberately public (load balancers / uptime checks).
api_router.include_router(health.router)

protected = [Depends(verify_api_key)]
api_router.include_router(system.router, dependencies=protected)
api_router.include_router(documents.router, dependencies=protected)
api_router.include_router(ingestion.router, dependencies=protected)
api_router.include_router(chat.router, dependencies=protected)
api_router.include_router(retrieval.router, dependencies=protected)
api_router.include_router(evaluation.router, dependencies=protected)
