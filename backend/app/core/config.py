"""Validated application configuration (Pydantic Settings).

Required vs optional values:

* ``OPENAI_API_KEY`` – required for ingestion, chat and evaluation. Required at startup
  when ``ENVIRONMENT=production``; in development the app starts without it so that
  health checks, document listing and tests work, but paid endpoints return 503.
* ``API_KEY`` – application key expected in the ``X-API-Key`` header. Required when
  ``ENVIRONMENT=production``. When empty in development, authentication is disabled and a
  warning is surfaced via ``/api/v1/config``.
* Everything else has a safe default for local development.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Native output dimensions of OpenAI embedding models. Used to size the Qdrant collection.
KNOWN_EMBEDDING_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "production", "test"] = "development"
    app_name: str = "Production RAG Platform"

    # OpenAI
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int | None = Field(
        default=None,
        description="Override the embedding size (text-embedding-3-* only). "
        "Defaults to the model's native dimension.",
    )
    openai_timeout_seconds: float = Field(default=60.0, gt=0)
    openai_max_retries: int = Field(default=3, ge=0, le=10)
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)
    llm_temperature: float | None = Field(
        default=0.0, ge=0.0, le=2.0, description="Leave empty for models that reject it."
    )
    llm_max_tokens: int = Field(default=800, ge=16, le=8192)

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_path: str | None = Field(
        default=None,
        description="Embedded on-disk Qdrant (local mode). Development only; "
        "takes precedence over QDRANT_URL when set.",
    )
    qdrant_collection_name: str = "rag_documents"
    qdrant_timeout_seconds: int = Field(default=10, gt=0)

    # Chunking / retrieval
    chunk_size: int = Field(default=800, ge=100, le=8000)
    chunk_overlap: int = Field(default=120, ge=0)
    retrieval_top_k: int = Field(default=10, ge=1, le=100)
    rerank_top_k: int = Field(default=4, ge=1, le=50)
    rrf_k: int = Field(default=60, ge=1)
    dense_weight: float = Field(default=1.0, ge=0.0)
    bm25_weight: float = Field(default=1.0, ge=0.0)

    # Reranker
    reranker_enabled: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_fallback: Literal["error", "fusion"] = Field(
        default="error",
        description="Behaviour when the cross-encoder cannot initialise: 'error' fails "
        "requests clearly, 'fusion' explicitly falls back to fused-rank order.",
    )
    reranker_preload: bool = Field(default=False, description="Load the model at startup.")
    rerank_min_score: float | None = Field(
        default=None,
        description="Optional cross-encoder score below which chunks are discarded.",
    )

    # Observability
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "production-rag-platform"
    langsmith_endpoint: str | None = None
    langsmith_hide_content: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # Cache
    redis_url: str | None = None
    enable_cache: bool = False
    cache_ttl_seconds: int = Field(default=3600, ge=1)

    # Security / API
    api_key: SecretStr | None = None
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    max_upload_size_mb: int = Field(default=20, ge=1, le=200)
    max_files_per_upload: int = Field(default=10, ge=1, le=50)
    max_question_chars: int = Field(default=2000, ge=10)
    rate_limit_per_minute: int = Field(
        default=30, ge=0, description="Per-client limit for expensive endpoints; 0 disables."
    )
    ingestion_concurrency: int = Field(default=2, ge=1, le=8)
    request_timeout_seconds: float = Field(default=120.0, gt=0)

    # Persistence
    data_dir: Path = BACKEND_ROOT / "data"
    evaluations_dir: Path = BACKEND_ROOT / "evaluations"
    max_eval_cases: int = Field(default=100, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator(
        "openai_api_key", "qdrant_api_key", "langsmith_api_key", "api_key", mode="before"
    )
    @classmethod
    def _empty_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("redis_url", "qdrant_path", "langsmith_endpoint", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("embedding_dimensions", "rerank_min_score", "llm_temperature", mode="before")
    @classmethod
    def _empty_number_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid LOG_LEVEL '{value}'")
        return value

    @model_validator(mode="after")
    def _cross_field_checks(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.rerank_top_k > self.retrieval_top_k:
            raise ValueError("RERANK_TOP_K must be less than or equal to RETRIEVAL_TOP_K")
        if self.enable_cache and not self.redis_url:
            raise ValueError("ENABLE_CACHE=true requires REDIS_URL")
        if self.langsmith_tracing and self.langsmith_api_key is None:
            raise ValueError("LANGSMITH_TRACING=true requires LANGSMITH_API_KEY")
        if "*" in self.cors_origins:
            raise ValueError("Wildcard CORS_ORIGINS is not allowed; list explicit origins")
        if (
            self.openai_embedding_model not in KNOWN_EMBEDDING_DIMENSIONS
            and self.embedding_dimensions is None
        ):
            raise ValueError(
                f"Unknown embedding model '{self.openai_embedding_model}': "
                "set EMBEDDING_DIMENSIONS explicitly"
            )
        if self.environment == "production":
            missing = [
                name
                for name, val in (
                    ("OPENAI_API_KEY", self.openai_api_key),
                    ("API_KEY", self.api_key),
                )
                if val is None
            ]
            if missing:
                raise ValueError(f"Missing required production settings: {', '.join(missing)}")
            if self.qdrant_path:
                raise ValueError("QDRANT_PATH (embedded Qdrant) is not supported in production")
        return self

    # Derived helpers -------------------------------------------------------------------
    @property
    def vector_size(self) -> int:
        return self.embedding_dimensions or KNOWN_EMBEDDING_DIMENSIONS[self.openai_embedding_model]

    @property
    def auth_enabled(self) -> bool:
        return self.api_key is not None

    @property
    def openai_configured(self) -> bool:
        return self.openai_api_key is not None

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def cache_active(self) -> bool:
        return self.enable_cache and bool(self.redis_url)

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def upload_tmp_dir(self) -> Path:
        return self.data_dir / "uploads"

    def warnings(self) -> list[str]:
        """Non-sensitive configuration warnings surfaced to the UI."""
        out: list[str] = []
        if not self.openai_configured:
            out.append("OPENAI_API_KEY is not set: ingestion, chat and evaluation are disabled.")
        if not self.auth_enabled:
            out.append("API_KEY is not set: the API is unauthenticated (development only).")
        if not self.reranker_enabled:
            out.append("Cross-encoder reranking is disabled; fused ranking order is used.")
        if self.qdrant_path:
            out.append("Using embedded Qdrant (QDRANT_PATH); use a Qdrant server in production.")
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
