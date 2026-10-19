from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal["pending", "processing", "indexed", "failed"]


class DocumentOut(BaseModel):
    document_id: str
    filename: str
    file_type: str
    size_bytes: int
    content_hash: str
    status: DocumentStatus
    error: str | None = None
    chunk_count: int = 0
    page_count: int | None = None
    embedding_model: str | None = None
    created_at: str
    updated_at: str
    indexed_at: str | None = None


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class DocumentDeleteResponse(BaseModel):
    document_id: str
    deleted: bool
    vectors_deleted: bool


class ChunkPayload(BaseModel):
    """Metadata stored with every vector in Qdrant."""

    document_id: str
    filename: str
    chunk_id: str
    chunk_index: int
    page_number: int | None = None
    source: str
    content: str
    content_hash: str
    ingestion_timestamp: str
    embedding_model: str
    char_count: int = Field(ge=0)
