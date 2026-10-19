"""Qdrant vector store wrapper.

Modes:
* Server (default): ``QDRANT_URL`` (+ optional ``QDRANT_API_KEY`` for Qdrant Cloud).
  Inside Docker Compose use the service hostname, e.g. ``http://qdrant:6333``.
* Embedded: ``QDRANT_PATH=./data/qdrant`` (on-disk, single process, development only) or
  ``:memory:`` (tests).

Embedding-model safety: the collection's vector size is checked against the configured
embedding dimension. On mismatch the store refuses reads/writes (``VectorDimensionMismatch``);
use ``scripts/reindex.py`` to migrate. We never recreate or alter a collection implicitly.
"""

from __future__ import annotations

import contextlib
import logging
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.core.config import Settings
from app.core.exceptions import ServiceUnavailable, UpstreamError, VectorDimensionMismatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DenseHit:
    chunk_id: str
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict[str, Any]


def build_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    if settings.qdrant_path:
        if settings.qdrant_path == ":memory:":
            return AsyncQdrantClient(location=":memory:")
        return AsyncQdrantClient(path=settings.qdrant_path)
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
        timeout=settings.qdrant_timeout_seconds,
    )


class VectorStore:
    def __init__(self, client: AsyncQdrantClient, collection: str, vector_size: int) -> None:
        self.client = client
        self.collection = collection
        self.vector_size = vector_size
        self.dimension_error: str | None = None
        self.initialized = False

    async def initialize(self) -> None:
        """Create the collection if missing and verify its vector size."""
        try:
            exists = await self.client.collection_exists(self.collection)
            if not exists:
                await self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self.vector_size, distance=models.Distance.COSINE
                    ),
                )
                logger.info("created qdrant collection", extra={"collection": self.collection})
            await self._ensure_payload_indexes()
            actual = await self.collection_vector_size()
        except Exception as exc:
            raise ServiceUnavailable(f"Qdrant is unavailable: {type(exc).__name__}") from exc
        if actual != self.vector_size:
            self.dimension_error = (
                f"Collection '{self.collection}' stores {actual}-dimensional vectors but the "
                f"configured embedding model produces {self.vector_size}. Run "
                "scripts/reindex.py or point QDRANT_COLLECTION_NAME at a new collection."
            )
            logger.error("vector dimension mismatch", extra={"detail": self.dimension_error})
        else:
            self.dimension_error = None
        self.initialized = True

    async def _ensure_payload_indexes(self) -> None:
        for field in ("document_id", "content_hash"):
            try:
                with warnings.catch_warnings():
                    # Embedded (local) Qdrant warns that payload indexes are no-ops there.
                    warnings.simplefilter("ignore", UserWarning)
                    await self.client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        wait=True,
                    )
            except Exception as exc:  # already exists / not supported
                logger.debug("payload index not created", extra={"field": field, "error": str(exc)})

    async def collection_vector_size(self) -> int:
        info = await self.client.get_collection(self.collection)
        vectors = info.config.params.vectors
        if isinstance(vectors, models.VectorParams):
            return vectors.size
        if isinstance(vectors, dict) and vectors:  # named vectors – not created by this app
            return next(iter(vectors.values())).size
        raise UpstreamError("Unsupported Qdrant collection vector configuration")

    def _require_usable(self) -> None:
        if not self.initialized:
            raise ServiceUnavailable("Vector store is not initialized (is Qdrant reachable?)")
        if self.dimension_error:
            raise VectorDimensionMismatch(self.dimension_error)

    @staticmethod
    def _document_filter(document_ids: list[str] | None) -> models.Filter | None:
        if not document_ids:
            return None
        return models.Filter(
            must=[models.FieldCondition(key="document_id", match=models.MatchAny(any=document_ids))]
        )

    async def upsert(self, points: list[VectorPoint], batch_size: int = 128) -> int:
        """Upsert and wait for confirmation. Raises if Qdrant does not report completion."""
        self._require_usable()
        written = 0
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            for p in batch:
                if len(p.vector) != self.vector_size:
                    raise VectorDimensionMismatch(
                        f"Vector of size {len(p.vector)} cannot be stored in a "
                        f"{self.vector_size}-dimensional collection"
                    )
            result = await self.client.upsert(
                collection_name=self.collection,
                points=[
                    models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in batch
                ],
                wait=True,
            )
            if result.status != models.UpdateStatus.COMPLETED:
                raise UpstreamError(f"Qdrant upsert not confirmed (status={result.status})")
            written += len(batch)
        return written

    async def search(
        self, vector: list[float], *, limit: int, document_ids: list[str] | None = None
    ) -> list[DenseHit]:
        self._require_usable()
        response = await self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            query_filter=self._document_filter(document_ids),
            with_payload=True,
            with_vectors=False,
        )
        return [
            DenseHit(chunk_id=str(p.id), score=float(p.score), payload=dict(p.payload or {}))
            for p in response.points
        ]

    async def delete_document(self, document_id: str) -> None:
        self._require_usable()
        result = await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(filter=self._document_filter([document_id])),
            wait=True,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise UpstreamError(f"Qdrant delete not confirmed (status={result.status})")

    async def count(self, document_id: str | None = None) -> int:
        result = await self.client.count(
            collection_name=self.collection,
            count_filter=self._document_filter([document_id] if document_id else None),
            exact=True,
        )
        return result.count

    async def scroll_payloads(
        self, page_size: int = 256
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield (point_id, payload) for every point – used to rebuild the BM25 index."""
        offset: Any = None
        while True:
            points, offset = await self.client.scroll(
                collection_name=self.collection,
                limit=page_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                yield str(p.id), dict(p.payload or {})
            if offset is None:
                break

    async def health(self) -> tuple[str, str | None]:
        try:
            await self.client.get_collections()
        except Exception as exc:
            return "down", f"Qdrant unreachable: {type(exc).__name__}"
        if self.dimension_error:
            return "degraded", "Vector dimension mismatch; see logs"
        if not self.initialized:
            return "degraded", "Collection not initialized"
        return "ok", None

    async def close(self) -> None:
        with contextlib.suppress(Exception):  # best effort on shutdown
            await self.client.close()
