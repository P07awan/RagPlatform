"""Hybrid retrieval: dense (Qdrant) + lexical (BM25) fused with Reciprocal Rank Fusion.

RRF score for a chunk = Σ_r  w_r / (k + rank_r)   (rank is 1-based, k defaults to 60).
RRF only uses ranks, so it needs no score normalization between cosine similarity and
BM25. Chunks are deduplicated by their stable ``chunk_id``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.rag.bm25_retriever import BM25Index
from app.rag.embeddings import Embedder
from app.rag.vector_store import DenseHit, VectorStore


@dataclass
class Candidate:
    chunk_id: str
    payload: dict[str, Any]
    dense_score: float | None = None
    dense_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None

    @property
    def content(self) -> str:
        return str(self.payload.get("content", ""))

    def to_dict(self) -> dict[str, Any]:
        p = self.payload
        return {
            "chunk_id": self.chunk_id,
            "document_id": p.get("document_id"),
            "filename": p.get("filename"),
            "chunk_index": p.get("chunk_index"),
            "page_number": p.get("page_number"),
            "content": self.content,
            "dense_score": self.dense_score,
            "dense_rank": self.dense_rank,
            "bm25_score": self.bm25_score,
            "bm25_rank": self.bm25_rank,
            "fused_score": self.fused_score,
            "rerank_score": self.rerank_score,
        }


@dataclass
class HybridResult:
    candidates: list[Candidate]
    dense_count: int
    bm25_count: int
    timings_ms: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(
    dense: list[DenseHit],
    lexical: list[tuple[str, float, dict[str, Any]]],
    *,
    k: int = 60,
    dense_weight: float = 1.0,
    bm25_weight: float = 1.0,
    limit: int | None = None,
) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for rank, hit in enumerate(dense, start=1):
        cand = merged.get(hit.chunk_id)
        if cand is None:
            cand = merged[hit.chunk_id] = Candidate(chunk_id=hit.chunk_id, payload=hit.payload)
        if cand.dense_rank is None:  # ignore duplicate entries from the same list
            cand.dense_rank, cand.dense_score = rank, hit.score
            cand.fused_score += dense_weight / (k + rank)
    for rank, (chunk_id, score, payload) in enumerate(lexical, start=1):
        cand = merged.get(chunk_id)
        if cand is None:
            cand = merged[chunk_id] = Candidate(chunk_id=chunk_id, payload=payload)
        if cand.bm25_rank is None:
            cand.bm25_rank, cand.bm25_score = rank, score
            cand.fused_score += bm25_weight / (k + rank)
    ranked = sorted(
        merged.values(),
        key=lambda c: (
            -c.fused_score,
            min(c.dense_rank or 10**9, c.bm25_rank or 10**9),
            c.chunk_id,
        ),
    )
    return ranked[:limit] if limit else ranked


class HybridRetriever:
    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        bm25: BM25Index,
        *,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        bm25_weight: float = 1.0,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.bm25 = bm25
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.bm25_weight = bm25_weight

    async def _dense(
        self, query: str, top_k: int, document_ids: list[str] | None
    ) -> tuple[list[DenseHit], float]:
        start = time.perf_counter()
        vector = await self.embedder.embed_query(query)
        hits = await self.vector_store.search(vector, limit=top_k, document_ids=document_ids)
        return hits, (time.perf_counter() - start) * 1000

    async def _lexical(
        self, query: str, top_k: int, document_ids: list[str] | None
    ) -> tuple[list[tuple[str, float, dict[str, Any]]], float]:
        start = time.perf_counter()
        hits = await asyncio.to_thread(self.bm25.search, query, top_k, document_ids)
        return [(h.chunk_id, h.score, h.payload) for h in hits], (
            time.perf_counter() - start
        ) * 1000

    async def retrieve(
        self, query: str, *, top_k: int, document_ids: list[str] | None = None
    ) -> HybridResult:
        (dense, dense_ms), (lexical, bm25_ms) = await asyncio.gather(
            self._dense(query, top_k, document_ids), self._lexical(query, top_k, document_ids)
        )
        fused = reciprocal_rank_fusion(
            dense,
            lexical,
            k=self.rrf_k,
            dense_weight=self.dense_weight,
            bm25_weight=self.bm25_weight,
            limit=top_k,
        )
        return HybridResult(
            candidates=fused,
            dense_count=len(dense),
            bm25_count=len(lexical),
            timings_ms={"dense_ms": round(dense_ms, 1), "bm25_ms": round(bm25_ms, 1)},
        )
