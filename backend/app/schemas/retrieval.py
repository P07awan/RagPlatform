from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.chat import RetrievedChunk


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    rerank_top_k: int | None = Field(default=None, ge=1, le=50)
    rerank: bool = True
    document_ids: list[str] | None = Field(default=None, max_length=50)


class SearchResponse(BaseModel):
    query: str
    dense_candidates: int
    bm25_candidates: int
    fused: list[RetrievedChunk]
    reranked: list[RetrievedChunk]
    rerank_applied: bool
    rerank_mode: str
    latency_ms: dict[str, float]
