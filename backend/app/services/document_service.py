"""Document upload, ingestion, listing and deletion.

Ingestion flow per file:
  stream upload to a temp file (hash + size check) → validate → duplicate check →
  register (pending) → background task: extract → clean → chunk → embed → upsert (wait)
  → BM25 sync → status=indexed. Any failure sets status=failed with a client-safe reason
  and removes any partially written vectors.

Background jobs run in-process (asyncio tasks, bounded by a semaphore). They are NOT a
durable queue: if the process restarts, in-flight documents are marked failed on startup
and must be re-uploaded. For heavy production workloads move ingestion to a worker queue
(e.g. Celery/RQ/Arq) – the ``ingest`` method is already self-contained for that.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.rag.bm25_retriever import BM25Index
from app.rag.chunking import chunk_document
from app.rag.embeddings import Embedder
from app.rag.loaders import DocumentLoadError, load_document
from app.rag.vector_store import VectorPoint, VectorStore
from app.schemas.documents import DocumentOut
from app.schemas.ingestion import FileUploadResult, UploadResponse
from app.services.cache import AnswerCache
from app.storage.sqlite_store import AsyncStore, utcnow
from app.utils.file_validation import (
    FileValidationError,
    validate_content_header,
    validate_filename,
)
from app.utils.text_processing import sha256_hex

logger = logging.getLogger(__name__)

READ_CHUNK = 1024 * 1024
SNIFF_BYTES = 2048


class _TooLarge(Exception):
    pass


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        store: AsyncStore,
        vector_store: VectorStore,
        bm25: BM25Index,
        embedder: Embedder,
        cache: AnswerCache,
    ) -> None:
        self.settings = settings
        self.store = store
        self.vector_store = vector_store
        self.bm25 = bm25
        self.embedder = embedder
        self.cache = cache
        self._semaphore = asyncio.Semaphore(settings.ingestion_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()
        settings.upload_tmp_dir.mkdir(parents=True, exist_ok=True)

    # Upload ------------------------------------------------------------------------------
    async def _spool(self, upload: UploadFile) -> tuple[Path, str, int, bytes]:
        """Copy the upload to a server-named temp file, hashing and enforcing size."""
        hasher = hashlib.sha256()
        size = 0
        head = b""
        fd, name = tempfile.mkstemp(
            prefix="upload-", suffix=".bin", dir=self.settings.upload_tmp_dir
        )
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := await upload.read(READ_CHUNK):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise _TooLarge
                    if len(head) < SNIFF_BYTES:
                        head += chunk[: SNIFF_BYTES - len(head)]
                    hasher.update(chunk)
                    out.write(chunk)
        except BaseException:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        return path, hasher.hexdigest(), size, head

    async def upload(self, files: list[UploadFile], *, wait: bool = False) -> UploadResponse:
        results: list[FileUploadResult] = []
        jobs: list[tuple[int, asyncio.Task[None]]] = []
        for upload in files:
            display_name = upload.filename or "unnamed"
            try:
                meta = validate_filename(upload.filename)
                display_name = meta.safe_name
                path, content_hash, size, head = await self._spool(upload)
            except FileValidationError as exc:
                results.append(
                    FileUploadResult(filename=display_name, outcome="rejected", message=str(exc))
                )
                continue
            except _TooLarge:
                results.append(
                    FileUploadResult(
                        filename=display_name,
                        outcome="rejected",
                        message=f"File exceeds the {self.settings.max_upload_size_mb} MB limit",
                    )
                )
                continue
            finally:
                await upload.close()

            try:
                validate_content_header(head, meta.file_type)
            except FileValidationError as exc:
                path.unlink(missing_ok=True)
                results.append(
                    FileUploadResult(filename=display_name, outcome="rejected", message=str(exc))
                )
                continue

            existing = await self.store.find_document_by_hash(content_hash)
            if existing and existing["status"] in {"indexed", "pending", "processing"}:
                path.unlink(missing_ok=True)
                results.append(
                    FileUploadResult(
                        filename=display_name,
                        outcome="duplicate",
                        document_id=existing["document_id"],
                        message=f"Identical content already {existing['status']} as "
                        f"'{existing['filename']}'",
                        document=DocumentOut(**existing),
                    )
                )
                continue

            if existing and existing["status"] == "failed":
                # Retry: reuse the failed record so history stays in one place.
                document_id = existing["document_id"]
                await self.store.update_document(
                    document_id, status="pending", error=None, filename=display_name, chunk_count=0
                )
            else:
                document_id = uuid.uuid4().hex
                await self.store.create_document(
                    {
                        "document_id": document_id,
                        "filename": display_name,
                        "file_type": meta.file_type,
                        "size_bytes": size,
                        "content_hash": content_hash,
                        "status": "pending",
                    }
                )
            task = asyncio.create_task(
                self.ingest(document_id, path, meta.file_type, display_name, content_hash),
                name=f"ingest-{document_id}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            results.append(
                FileUploadResult(
                    filename=display_name,
                    outcome="accepted",
                    document_id=document_id,
                    message="Queued for ingestion",
                )
            )
            jobs.append((len(results) - 1, task))

        if wait and jobs:
            await asyncio.gather(*(t for _, t in jobs), return_exceptions=True)
            for idx, _ in jobs:
                res = results[idx]
                doc = await self.store.get_document(res.document_id)  # type: ignore[arg-type]
                if doc:
                    res.document = DocumentOut(**doc)
                    res.outcome = "indexed" if doc["status"] == "indexed" else "failed"
                    res.message = doc["error"] or f"Indexed {doc['chunk_count']} chunks"

        accepted = sum(r.outcome in {"accepted", "indexed"} for r in results)
        return UploadResponse(results=results, accepted=accepted, rejected=len(results) - accepted)

    # Ingestion ---------------------------------------------------------------------------
    async def ingest(
        self, document_id: str, path: Path, file_type: str, filename: str, content_hash: str
    ) -> None:
        vectors_written = False
        try:
            async with self._semaphore:
                await self.store.update_document(document_id, status="processing")
                loaded = await asyncio.to_thread(load_document, path, file_type)
                chunks = chunk_document(
                    loaded,
                    document_id=document_id,
                    file_type=file_type,
                    chunk_size=self.settings.chunk_size,
                    chunk_overlap=self.settings.chunk_overlap,
                )
                if not chunks:
                    raise DocumentLoadError("No text chunks could be produced from this document")
                vectors = await self.embedder.embed_documents([c.text for c in chunks])
                timestamp = datetime.now(UTC).isoformat()
                points: list[VectorPoint] = []
                bm25_items: list[tuple[str, str, dict[str, Any]]] = []
                for chunk, vector in zip(chunks, vectors, strict=True):
                    payload = {
                        "document_id": document_id,
                        "filename": filename,
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "source": f"{filename}#chunk-{chunk.chunk_index}",
                        "content": chunk.text,
                        "content_hash": sha256_hex(chunk.text),
                        "document_hash": content_hash,
                        "ingestion_timestamp": timestamp,
                        "embedding_model": self.embedder.model,
                        "char_count": len(chunk.text),
                    }
                    points.append(VectorPoint(id=chunk.chunk_id, vector=vector, payload=payload))
                    bm25_items.append((chunk.chunk_id, chunk.text, payload))
                vectors_written = True  # from here on, clean up on failure
                await self.vector_store.upsert(points)
                await asyncio.to_thread(self.bm25.add_many, bm25_items)
                await self.store.update_document(
                    document_id,
                    status="indexed",
                    chunk_count=len(chunks),
                    page_count=loaded.page_count,
                    embedding_model=self.embedder.model,
                    indexed_at=utcnow(),
                    error=None,
                )
            await self.cache.invalidate()
            logger.info(
                "document indexed", extra={"document_id": document_id, "chunks": len(chunks)}
            )
        except Exception as exc:
            message = self._failure_message(exc)
            log = (
                logger.warning
                if isinstance(exc, (DocumentLoadError, AppError))
                else logger.exception
            )
            log("ingestion failed", extra={"document_id": document_id, "error": message})
            if vectors_written:
                await self._cleanup_vectors(document_id)
            try:
                await self.store.update_document(document_id, status="failed", error=message)
            except Exception:  # pragma: no cover - store failure while recording failure
                logger.exception("could not record ingestion failure")
        finally:
            await asyncio.to_thread(path.unlink, missing_ok=True)

    @staticmethod
    def _failure_message(exc: Exception) -> str:
        if isinstance(exc, DocumentLoadError):
            return str(exc)
        if isinstance(exc, AppError):
            return exc.message
        return "Unexpected ingestion error; see server logs"

    async def _cleanup_vectors(self, document_id: str) -> None:
        try:
            await asyncio.to_thread(self.bm25.remove_document, document_id)
            await self.vector_store.delete_document(document_id)
        except Exception:
            logger.exception(
                "failed to clean up partial vectors", extra={"document_id": document_id}
            )

    # Queries -----------------------------------------------------------------------------
    async def list(
        self, *, limit: int, offset: int, status: str | None
    ) -> tuple[list[DocumentOut], int]:
        rows, total = await self.store.list_documents(limit=limit, offset=offset, status=status)
        return [DocumentOut(**r) for r in rows], total

    async def get(self, document_id: str) -> DocumentOut:
        row = await self.store.get_document(document_id)
        if row is None:
            raise NotFoundError(f"Document '{document_id}' not found")
        return DocumentOut(**row)

    async def delete(self, document_id: str) -> bool:
        row = await self.store.get_document(document_id)
        if row is None:
            raise NotFoundError(f"Document '{document_id}' not found")
        if row["status"] in {"pending", "processing"}:
            raise ConflictError("Document is still being ingested; try again when it finishes")
        # Vectors first: if Qdrant fails we keep the record so deletion can be retried.
        await self.vector_store.delete_document(document_id)
        await asyncio.to_thread(self.bm25.remove_document, document_id)
        await self.store.delete_document(document_id)
        await self.cache.invalidate()
        logger.info("document deleted", extra={"document_id": document_id})
        return True

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
