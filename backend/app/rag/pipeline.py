"""High-level RAG pipeline facade used by services (chat, retrieval, evaluation)."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, UpstreamTimeout
from app.rag.bm25_retriever import BM25Index
from app.rag.embeddings import Embedder
from app.rag.generator import AnswerGenerator
from app.rag.graph import GraphDeps, RAGState, build_graph
from app.rag.hybrid_retriever import HybridRetriever
from app.rag.reranker import CrossEncoderReranker
from app.rag.vector_store import VectorStore
from app.services.cache import AnswerCache


class UnconfiguredEmbedder:
    """Placeholder used when OPENAI_API_KEY is missing: fails clearly on use."""

    def __init__(self, model: str, dimensions: int) -> None:
        self.model = model
        self.dimensions = dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ConfigurationError("OPENAI_API_KEY is not configured; embeddings are unavailable")

    async def embed_query(self, text: str) -> list[float]:
        raise ConfigurationError("OPENAI_API_KEY is not configured; embeddings are unavailable")


class UnconfiguredGenerator:
    def __init__(self, model: str) -> None:
        self.model = model

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        raise ConfigurationError("OPENAI_API_KEY is not configured; generation is unavailable")
        yield ""  # pragma: no cover - makes this an async generator


class RAGPipeline:
    def __init__(
        self,
        settings: Settings,
        *,
        embedder: Embedder,
        vector_store: VectorStore,
        bm25: BM25Index,
        reranker: CrossEncoderReranker,
        generator: AnswerGenerator,
        cache: AnswerCache,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.vector_store = vector_store
        self.bm25 = bm25
        self.reranker = reranker
        self.generator = generator
        self.cache = cache
        self.retriever = HybridRetriever(
            embedder,
            vector_store,
            bm25,
            rrf_k=settings.rrf_k,
            dense_weight=settings.dense_weight,
            bm25_weight=settings.bm25_weight,
        )
        self.graph = build_graph(
            GraphDeps(
                embedder=embedder,
                vector_store=vector_store,
                bm25=bm25,
                reranker=reranker,
                generator=generator,
                cache=cache,
                rrf_k=settings.rrf_k,
                dense_weight=settings.dense_weight,
                bm25_weight=settings.bm25_weight,
                max_question_chars=settings.max_question_chars,
            )
        )

    def initial_state(
        self,
        question: str,
        *,
        session_id: str | None = None,
        document_ids: list[str] | None = None,
        use_cache: bool = True,
    ) -> RAGState:
        return {
            "question": question,
            "session_id": session_id or uuid.uuid4().hex,
            "document_ids": document_ids or None,
            "top_k": self.settings.retrieval_top_k,
            "rerank_top_k": self.settings.rerank_top_k,
            "use_cache": use_cache,
            "started_at": time.perf_counter(),
        }

    async def run(self, state: RAGState) -> RAGState:
        config = {"run_name": "rag_chat", "metadata": {"session_id": state.get("session_id")}}
        try:
            return await asyncio.wait_for(
                self.graph.ainvoke(state, config=config),
                timeout=self.settings.request_timeout_seconds,
            )
        except TimeoutError as exc:
            raise UpstreamTimeout("The RAG pipeline timed out") from exc

    async def stream(self, state: RAGState) -> AsyncIterator[tuple[str, Any]]:
        """Yield ("event", dict) for custom node events and ("final", state) at the end."""
        config = {
            "run_name": "rag_chat_stream",
            "metadata": {"session_id": state.get("session_id")},
        }
        final: dict[str, Any] = dict(state)
        deadline = time.monotonic() + self.settings.request_timeout_seconds
        async for mode, chunk in self.graph.astream(
            state, config=config, stream_mode=["custom", "values"]
        ):
            if time.monotonic() > deadline:
                raise UpstreamTimeout("The RAG pipeline timed out")
            if mode == "custom":
                yield "event", chunk
            elif mode == "values":
                final = chunk
        yield "final", final

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        rerank_top_k: int | None = None,
        rerank: bool = True,
        document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        top_k = top_k or self.settings.retrieval_top_k
        rerank_top_k = min(rerank_top_k or self.settings.rerank_top_k, top_k)
        start = time.perf_counter()
        result = await self.retriever.retrieve(query, top_k=top_k, document_ids=document_ids)
        retrieval_ms = (time.perf_counter() - start) * 1000
        fused_snapshot = [c.to_dict() for c in result.candidates]
        if rerank:
            outcome = await self.reranker.rerank(query, result.candidates, rerank_top_k)
            reranked, mode, rerank_ms = outcome.candidates, outcome.mode, outcome.duration_ms
        else:
            reranked, mode, rerank_ms = result.candidates[:rerank_top_k], "disabled", 0.0
        return {
            "query": query,
            "dense_candidates": result.dense_count,
            "bm25_candidates": result.bm25_count,
            "fused": fused_snapshot,
            "reranked": [c.to_dict() for c in reranked],
            "rerank_applied": mode == "cross_encoder",
            "rerank_mode": mode,
            "latency_ms": {
                **result.timings_ms,
                "retrieval_ms": round(retrieval_ms, 1),
                "rerank_ms": round(rerank_ms, 1),
            },
        }
