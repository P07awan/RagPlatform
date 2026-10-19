from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    document_ids: list[str] | None = Field(
        default=None, max_length=50, description="Restrict retrieval to these documents."
    )
    include_retrieval: bool = Field(default=True, description="Return retrieval diagnostics.")

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class Citation(BaseModel):
    index: int = Field(description="The [n] marker used in the answer.")
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None = Field(
        default=None, description="Null when the source format has no page metadata."
    )
    chunk_index: int
    excerpt: str
    score: float | None = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    chunk_index: int
    page_number: int | None = None
    content: str
    dense_score: float | None = None
    dense_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    fused_score: float | None = None
    rerank_score: float | None = None


class LatencyBreakdown(BaseModel):
    retrieval_ms: float | None = None
    rerank_ms: float | None = None
    generation_ms: float | None = None
    total_ms: float | None = None


class RetrievalMetadata(BaseModel):
    dense_candidates: int
    bm25_candidates: int
    fused_candidates: int
    reranked: bool
    rerank_mode: str
    chunks: list[RetrievedChunk] = []


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    session_id: str
    request_id: str | None
    insufficient_context: bool
    cache_hit: bool
    model: str
    latency: LatencyBreakdown
    retrieval: RetrievalMetadata | None = None
