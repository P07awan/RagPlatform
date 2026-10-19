"""Optional Redis answer cache.

Key = sha256(scope | normalized question | document filter | model | embedding model |
retrieval params | corpus version). The *corpus version* is a counter bumped on every
ingestion/deletion, so cached answers are invalidated whenever indexed content changes.
``scope`` isolates tenants; this single-user build uses one scope ("default"). A
multi-user build must use the authenticated user/tenant ID so cached answers are never
shared across users with different document access.

Outage policy: fail open. Redis errors are logged, the request continues uncached, and
Redis is not retried for ``COOLDOWN_SECONDS`` to avoid adding latency to every request.
Errors and insufficient-context answers are never cached.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from typing import Any

from app.core.config import Settings
from app.utils.text_processing import normalize_query, sha256_hex

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 30
VERSION_KEY = "rag:corpus_version"


class AnswerCache:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.enabled = settings.cache_active
        self._client = client
        self._down_until = 0.0
        self.hits = 0
        self.misses = 0
        self.errors = 0

    def _redis(self) -> Any | None:
        if not self.enabled or time.monotonic() < self._down_until:
            return None
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(
                self.settings.redis_url,  # type: ignore[arg-type]
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
                decode_responses=True,
            )
        return self._client

    def _mark_down(self, exc: Exception) -> None:
        self.errors += 1
        self._down_until = time.monotonic() + COOLDOWN_SECONDS
        logger.warning("redis unavailable; caching bypassed", extra={"error": type(exc).__name__})

    async def _corpus_version(self, client: Any) -> str:
        return str(await client.get(VERSION_KEY) or "0")

    def build_key(
        self, question: str, document_ids: list[str] | None, version: str, scope: str = "default"
    ) -> str:
        s = self.settings
        parts = [
            scope,
            normalize_query(question),
            ",".join(sorted(document_ids or [])),
            s.openai_model,
            s.openai_embedding_model,
            str(s.vector_size),
            f"{s.retrieval_top_k}/{s.rerank_top_k}/{s.rrf_k}/{s.reranker_enabled}/{s.reranker_model}",
            s.qdrant_collection_name,
            version,
        ]
        return "rag:answer:" + sha256_hex("|".join(parts))

    async def get(self, question: str, document_ids: list[str] | None) -> dict[str, Any] | None:
        client = self._redis()
        if client is None:
            return None
        try:
            key = self.build_key(question, document_ids, await self._corpus_version(client))
            raw = await client.get(key)
        except Exception as exc:
            self._mark_down(exc)
            return None
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(raw)

    async def set(
        self, question: str, document_ids: list[str] | None, value: dict[str, Any]
    ) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            key = self.build_key(question, document_ids, await self._corpus_version(client))
            await client.set(key, json.dumps(value), ex=self.settings.cache_ttl_seconds)
        except Exception as exc:
            self._mark_down(exc)

    async def invalidate(self) -> None:
        """Bump the corpus version (called after ingestion/deletion)."""
        client = self._redis()
        if client is None:
            return
        try:
            await client.incr(VERSION_KEY)
        except Exception as exc:
            self._mark_down(exc)

    async def ping(self) -> str:
        if not self.enabled:
            return "disabled"
        client = self._redis()
        if client is None:
            return "down"
        try:
            await client.ping()
            return "ok"
        except Exception as exc:
            self._mark_down(exc)
            return "down"

    async def close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):  # best effort on shutdown
                await self._client.aclose()
