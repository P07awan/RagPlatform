from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.documents import DocumentOut

UploadOutcome = Literal["accepted", "indexed", "duplicate", "rejected", "failed"]


class FileUploadResult(BaseModel):
    filename: str
    outcome: UploadOutcome
    document_id: str | None = None
    message: str | None = None
    document: DocumentOut | None = None


class UploadResponse(BaseModel):
    results: list[FileUploadResult]
    accepted: int
    rejected: int
