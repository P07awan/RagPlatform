"""Application container: builds and owns all long-lived components.

Created once in the FastAPI lifespan and stored on ``app.state.container``. Tests build
it with fakes via the ``overrides`` arguments.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, ServiceUnavailable, VectorDimensionMismatch
from app.core.security import SlidingWindowRateLimiter
from app.core.tracing import configure_tracing
from app.rag.bm25_retriever import BM25Index
from app.rag.embeddings import Embedder, OpenAIEmbedder
from app.rag.generator import AnswerGenerator, OpenAIGenerator
from app.rag.openai_client import build_openai_client
from app.rag.pipeline import RAGPipeline, UnconfiguredEmbedder, UnconfiguredGenerator
from app.rag.reranker import CrossEncoderReranker
from app.rag.vector_store import VectorStore, build_qdrant_client
from app.schemas.system import ComponentStatus, ConfigStatus, DashboardStats
from app.services.cache import AnswerCache
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.storage.sqlite_store import AsyncStore, SQLiteStore
from app.utils.file_validation import ALLOWED_EXTENSIONS

logger = logging.getLogger(__name__)


class AppContainer:
    def __init__(
        self,
        settings: Settings,
        *,
        embedder: Embedder | None = None,
        generator: AnswerGenerator | None = None,
        reranker: CrossEncoderReranker | None = None,
        vector_store: VectorStore | None = None,
        cache: AnswerCache | None = None,
        store: SQLiteStore | None = None,
        evaluation_backend: Any | None = None,
    ) -> None:
        self.settings = settings
        self.tracing_enabled = configure_tracing(settings)

        self.store = AsyncStore(store or SQLiteStore(settings.sqlite_path))
        self.vector_store = vector_store or VectorStore(
            build_qdrant_client(settings), settings.qdrant_collection_name, settings.vector_size
        )
        self.bm25 = BM25Index()
        self.cache = cache or AnswerCache(settings)

        openai_client = None
        if (embedder is None or generator is None) and settings.openai_configured:
            openai_client = build_openai_client(settings)
        if embedder is None:
            embedder = (
                OpenAIEmbedder.from_settings(openai_client, settings)
                if openai_client
                else UnconfiguredEmbedder(settings.openai_embedding_model, settings.vector_size)
            )
        if generator is None:
            generator = (
                OpenAIGenerator(
                    openai_client,
                    model=settings.openai_model,
                    temperature=settings.llm_temperature,
                    max_tokens=settings.llm_max_tokens,
                )
                if openai_client
                else UnconfiguredGenerator(settings.openai_model)
            )
        self.embedder = embedder
        self.generator = generator
        self.reranker = reranker or CrossEncoderReranker(
            settings.reranker_model,
            enabled=settings.reranker_enabled,
            fallback=settings.reranker_fallback,
            min_score=settings.rerank_min_score,
        )
        self.pipeline = RAGPipeline(
            settings,
            embedder=self.embedder,
            vector_store=self.vector_store,
            bm25=self.bm25,
            reranker=self.reranker,
            generator=self.generator,
            cache=self.cache,
        )
        self.documents = DocumentService(
            settings, self.store, self.vector_store, self.bm25, self.embedder, self.cache
        )
        self.chat = ChatService(settings, self.pipeline, self.store)
        self.evaluations = EvaluationService(
            settings, self.store, self.pipeline, self.vector_store, backend=evaluation_backend
        )
        self.rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)
        self._reranker_task: asyncio.Task[Any] | None = None

    # Lifecycle ---------------------------------------------------------------------------
    async def startup(self) -> None:
        interrupted_docs = await self.store.mark_interrupted_documents()
        interrupted_evals = await self.store.mark_interrupted_evaluations()
        if interrupted_docs or interrupted_evals:
            logger.warning(
                "marked interrupted jobs as failed",
                extra={"documents": interrupted_docs, "evaluations": interrupted_evals},
            )
        try:
            await self.vector_store.initialize()
            await self.rebuild_bm25()
        except ServiceUnavailable as exc:
            # Start degraded so /health and /ready can report the problem.
            logger.error("vector store unavailable at startup", extra={"error": exc.message})
        if self.settings.reranker_enabled and self.settings.reranker_preload:
            self._reranker_task = asyncio.create_task(asyncio.to_thread(self.reranker.load))

    async def rebuild_bm25(self) -> int:
        """Rebuild the lexical index from chunk payloads stored in Qdrant."""
        if self.vector_store.dimension_error:
            return 0
        items = []
        async for chunk_id, payload in self.vector_store.scroll_payloads():
            if "content" in payload and "document_id" in payload:
                items.append((chunk_id, payload["content"], payload))
        await asyncio.to_thread(self._replace_bm25, items)
        logger.info("bm25 index rebuilt", extra={"chunks": len(items)})
        return len(items)

    def _replace_bm25(self, items: list[tuple[str, str, dict[str, Any]]]) -> None:
        self.bm25.clear()
        self.bm25.add_many(items)
        self.bm25.loaded = True

    async def shutdown(self) -> None:
        await self.documents.shutdown()
        await self.evaluations.shutdown()
        if self._reranker_task:
            self._reranker_task.cancel()
        await self.cache.close()
        await self.vector_store.close()
        self.store.sync.close()

    # Guards ------------------------------------------------------------------------------
    def require_ingestion_ready(self) -> None:
        if not self.settings.openai_configured and isinstance(self.embedder, UnconfiguredEmbedder):
            raise ConfigurationError("OPENAI_API_KEY is not configured; ingestion is unavailable")
        if not self.vector_store.initialized:
            raise ServiceUnavailable("Vector store is not available; check Qdrant")
        if self.vector_store.dimension_error:
            raise VectorDimensionMismatch(self.vector_store.dimension_error)

    # Status ------------------------------------------------------------------------------
    async def component_status(self) -> dict[str, ComponentStatus]:
        q_state, q_detail = await self.vector_store.health()
        if q_state == "degraded" and not self.vector_store.initialized:
            # Qdrant came back after a failed startup: initialise lazily.
            try:
                await self.vector_store.initialize()
                await self.rebuild_bm25()
                q_state, q_detail = await self.vector_store.health()
            except ServiceUnavailable as exc:
                q_state, q_detail = "down", exc.message
        cache_state = await self.cache.ping()
        reranker_state = self.reranker.state
        return {
            "qdrant": ComponentStatus(status=q_state, detail=q_detail),  # type: ignore[arg-type]
            "openai": ComponentStatus(
                status="ok"
                if not isinstance(self.embedder, UnconfiguredEmbedder)
                else "not_configured",
                detail=None if self.settings.openai_configured else "OPENAI_API_KEY missing",
            ),
            "reranker": ComponentStatus(
                status={
                    "loaded": "ok",
                    "not_loaded": "ok",
                    "disabled": "disabled",
                    "failed": "degraded",
                }[reranker_state],  # type: ignore[arg-type]
                detail={
                    "not_loaded": "Loads on first use",
                    "failed": "Model failed to load; see logs",
                }.get(reranker_state),
            ),
            "cache": ComponentStatus(status=cache_state),  # type: ignore[arg-type]
            "tracing": ComponentStatus(status="ok" if self.tracing_enabled else "disabled"),
        }

    def config_status(self) -> ConfigStatus:
        s = self.settings
        return ConfigStatus(
            environment=s.environment,
            llm_model=s.openai_model,
            embedding_model=s.openai_embedding_model,
            vector_size=s.vector_size,
            collection=s.qdrant_collection_name,
            chunk_size=s.chunk_size,
            chunk_overlap=s.chunk_overlap,
            retrieval_top_k=s.retrieval_top_k,
            rerank_top_k=s.rerank_top_k,
            rrf_k=s.rrf_k,
            reranker_enabled=s.reranker_enabled,
            reranker_model=s.reranker_model,
            reranker_fallback=s.reranker_fallback,
            reranker_state=self.reranker.state,
            cache_enabled=s.cache_active,
            tracing_enabled=self.tracing_enabled,
            langsmith_project=s.langsmith_project if self.tracing_enabled else None,
            auth_enabled=s.auth_enabled,
            openai_configured=not isinstance(self.embedder, UnconfiguredEmbedder),
            max_upload_size_mb=s.max_upload_size_mb,
            allowed_extensions=sorted(ALLOWED_EXTENSIONS),
            warnings=s.warnings(),
        )

    async def dashboard_stats(self) -> DashboardStats:
        counts = await self.store.document_status_counts()
        recent_docs, total = await self.store.list_documents(limit=5, offset=0)
        try:
            chunks: int | None = (
                await self.vector_store.count() if self.vector_store.initialized else None
            )
        except Exception:
            chunks = None
        runs, _ = await self.store.list_evaluations(limit=1, offset=0)
        return DashboardStats(
            documents_total=total,
            documents_by_status=counts,
            chunks_indexed=chunks,
            recent_documents=recent_docs,
            recent_chats=await self.store.recent_chats(limit=8),
            last_evaluation=runs[0] if runs else None,
        )
