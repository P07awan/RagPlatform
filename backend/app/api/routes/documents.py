from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import get_container
from app.core.container import AppContainer
from app.core.exceptions import ValidationFailed
from app.core.security import rate_limit
from app.schemas.documents import DocumentDeleteResponse, DocumentList, DocumentOut, DocumentStatus
from app.schemas.ingestion import UploadResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit)],
    summary="Upload and ingest PDF/TXT/Markdown files",
)
async def upload_documents(
    files: Annotated[list[UploadFile], File(description="One or more files")],
    wait: Annotated[
        bool, Query(description="Block until ingestion finishes (small files / scripts)")
    ] = False,
    c: AppContainer = Depends(get_container),
) -> UploadResponse:
    if not files:
        raise ValidationFailed("No files provided")
    if len(files) > c.settings.max_files_per_upload:
        raise ValidationFailed(f"At most {c.settings.max_files_per_upload} files per upload")
    c.require_ingestion_ready()
    return await c.documents.upload(files, wait=wait)


@router.get("", response_model=DocumentList, summary="List documents with ingestion status")
async def list_documents(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    c: AppContainer = Depends(get_container),
) -> DocumentList:
    items, total = await c.documents.list(limit=limit, offset=offset, status=status_filter)
    return DocumentList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentOut, summary="Get document metadata")
async def get_document(document_id: str, c: AppContainer = Depends(get_container)) -> DocumentOut:
    return await c.documents.get(document_id)


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Delete a document and its vectors",
)
async def delete_document(
    document_id: str, c: AppContainer = Depends(get_container)
) -> DocumentDeleteResponse:
    await c.documents.delete(document_id)
    return DocumentDeleteResponse(document_id=document_id, deleted=True, vectors_deleted=True)
