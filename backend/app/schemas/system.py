from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ComponentState = Literal["ok", "degraded", "down", "disabled", "not_configured", "unknown"]


class ComponentStatus(BaseModel):
    status: ComponentState
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    components: dict[str, ComponentStatus]


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, ComponentStatus]


class ConfigStatus(BaseModel):
    environment: str
    llm_model: str
    embedding_model: str
    vector_size: int
    collection: str
    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int
    rerank_top_k: int
    rrf_k: int
    reranker_enabled: bool
    reranker_model: str
    reranker_fallback: str
    reranker_state: str
    cache_enabled: bool
    tracing_enabled: bool
    langsmith_project: str | None
    auth_enabled: bool
    openai_configured: bool
    max_upload_size_mb: int
    allowed_extensions: list[str]
    warnings: list[str]


class DashboardStats(BaseModel):
    documents_total: int
    documents_by_status: dict[str, int]
    chunks_indexed: int | None
    recent_documents: list[dict[str, object]]
    recent_chats: list[dict[str, object]]
    last_evaluation: dict[str, object] | None
