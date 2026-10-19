"""Ingestion status endpoints (lightweight polling for in-flight documents)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import AppContainer
from app.schemas.documents import DocumentOut

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.get(
    "/status/{document_id}", response_model=DocumentOut, summary="Ingestion status of one document"
)
async def ingestion_status(
    document_id: str, c: AppContainer = Depends(get_container)
) -> DocumentOut:
    return await c.documents.get(document_id)


@router.get("/summary", summary="Document counts by ingestion status")
async def ingestion_summary(c: AppContainer = Depends(get_container)) -> dict[str, int]:
    return await c.store.document_status_counts()
