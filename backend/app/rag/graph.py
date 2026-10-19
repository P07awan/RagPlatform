"""LangGraph RAG workflow.

    START → validate_request → check_cache ─(hit)──────────────────────────┐
                                   └─(miss)→ retrieve → fuse → rerank →    │
             check_context ─(insufficient)─┐                               │
                   └─(ok)→ generate → validate_output → finalize ←─────────┘ → END

Nodes are small async functions closing over injected dependencies, so each is testable
in isolation. During ``astream(stream_mode="custom")`` nodes emit progress events
(sources, tokens) through LangGraph's stream writer; with ``ainvoke`` the writer is a
no-op. State never contains secrets.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.core.exceptions import ValidationFailed
from app.rag.bm25_retriever import BM25Index
from app.rag.embeddings import Embedder
from app.rag.generator import AnswerGenerator
from app.rag.hybrid_retriever import Candidate, reciprocal_rank_fusion
from app.rag.prompts import INSUFFICIENT_CONTEXT_MESSAGE, build_messages
from app.rag.reranker import CrossEncoderReranker
from app.rag.vector_store import DenseHit, VectorStore
from app.services.cache import AnswerCache
from app.utils.text_processing import excerpt

_CITATION = re.compile(r"\[(\d{1,3})\]")


class RAGState(TypedDict, total=False):
    # Inputs
    question: str
    session_id: str
    document_ids: list[str] | None
    top_k: int
    rerank_top_k: int
    use_cache: bool
    # Intermediate
    dense_hits: list[DenseHit]
    lexical_hits: list[tuple[str, float, dict[str, Any]]]
    retrieved_documents: list[Candidate]
    reranked_documents: list[Candidate]
    rerank_mode: str
    # Outputs
    answer: str
    citations: list[dict[str, Any]]
    insufficient_context: bool
    cache_hit: bool
    cached_response: dict[str, Any] | None
    retrieval_scores: dict[str, int]
    latency: dict[str, float]
    errors: list[str]
    started_at: float


@dataclass
class GraphDeps:
    embedder: Embedder
    vector_store: VectorStore
    bm25: BM25Index
    reranker: CrossEncoderReranker
    generator: AnswerGenerator
    cache: AnswerCache
    rrf_k: int
    dense_weight: float
    bm25_weight: float
    max_question_chars: int


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _emit(event: dict[str, Any]) -> None:
    # Outside a LangGraph runnable context (e.g. a node unit-tested directly) there is no
    # stream writer; events are simply dropped.
    with contextlib.suppress(Exception):
        get_stream_writer()(event)


def extract_citations(
    answer: str, chunks: list[Candidate]
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Map [n] markers to retrieved chunks; strip markers that reference nothing."""
    citations: dict[int, dict[str, Any]] = {}
    invalid: set[int] = set()
    for match in _CITATION.finditer(answer):
        n = int(match.group(1))
        if 1 <= n <= len(chunks):
            if n not in citations:
                c = chunks[n - 1]
                p = c.payload
                citations[n] = {
                    "index": n,
                    "chunk_id": c.chunk_id,
                    "document_id": p["document_id"],
                    "filename": p["filename"],
                    "page_number": p.get("page_number"),
                    "chunk_index": p["chunk_index"],
                    "excerpt": excerpt(c.content),
                    "score": c.rerank_score if c.rerank_score is not None else c.fused_score,
                }
        else:
            invalid.add(n)
    errors: list[str] = []
    if invalid:
        answer = _CITATION.sub(lambda m: "" if int(m.group(1)) in invalid else m.group(0), answer)
        errors.append(f"Removed citation markers with no matching source: {sorted(invalid)}")
    return answer, sorted(citations.values(), key=lambda c: c["index"]), errors


def is_insufficient(answer: str) -> bool:
    head = " ".join(answer.strip().split()).lower()
    return head.startswith(INSUFFICIENT_CONTEXT_MESSAGE.lower().rstrip("."))


def build_graph(deps: GraphDeps):
    async def validate_request(state: RAGState) -> RAGState:
        question = " ".join(state.get("question", "").split())
        if not question:
            raise ValidationFailed("Question must not be empty")
        if len(question) > deps.max_question_chars:
            raise ValidationFailed(f"Question exceeds {deps.max_question_chars} characters")
        return {
            "question": question,
            "errors": [],
            "latency": {},
            "cache_hit": False,
            "started_at": state.get("started_at") or time.perf_counter(),
        }

    async def check_cache(state: RAGState) -> RAGState:
        if not state.get("use_cache", True) or not deps.cache.enabled:
            return {"cached_response": None}
        cached = await deps.cache.get(state["question"], state.get("document_ids"))
        if cached is None:
            return {"cached_response": None}
        _emit({"type": "sources", "chunks": [], "rerank_mode": None, "cache_hit": True})
        _emit({"type": "token", "text": cached["answer"]})
        return {
            "cached_response": cached,
            "cache_hit": True,
            "answer": cached["answer"],
            "citations": cached.get("citations", []),
            "insufficient_context": cached.get("insufficient_context", False),
        }

    async def retrieve(state: RAGState) -> RAGState:
        start = time.perf_counter()
        top_k, doc_ids = state["top_k"], state.get("document_ids")

        async def dense() -> list[DenseHit]:
            vector = await deps.embedder.embed_query(state["question"])
            return await deps.vector_store.search(vector, limit=top_k, document_ids=doc_ids)

        async def lexical() -> list[tuple[str, float, dict[str, Any]]]:
            hits = await asyncio.to_thread(deps.bm25.search, state["question"], top_k, doc_ids)
            return [(h.chunk_id, h.score, h.payload) for h in hits]

        dense_hits, lexical_hits = await asyncio.gather(dense(), lexical())
        return {
            "dense_hits": dense_hits,
            "lexical_hits": lexical_hits,
            "latency": {**state.get("latency", {}), "retrieval_ms": _ms(start)},
        }

    async def fuse(state: RAGState) -> RAGState:
        fused = reciprocal_rank_fusion(
            state["dense_hits"],
            state["lexical_hits"],
            k=deps.rrf_k,
            dense_weight=deps.dense_weight,
            bm25_weight=deps.bm25_weight,
            limit=state["top_k"],
        )
        return {
            "retrieved_documents": fused,
            "retrieval_scores": {
                "dense_candidates": len(state["dense_hits"]),
                "bm25_candidates": len(state["lexical_hits"]),
                "fused_candidates": len(fused),
            },
        }

    async def rerank(state: RAGState) -> RAGState:
        outcome = await deps.reranker.rerank(
            state["question"], state["retrieved_documents"], state["rerank_top_k"]
        )
        errors = list(state.get("errors", []))
        if outcome.mode == "fallback_fusion":
            errors.append("Reranker unavailable; using fused ranking order (fallback).")
        return {
            "reranked_documents": outcome.candidates,
            "rerank_mode": outcome.mode,
            "errors": errors,
            "latency": {**state.get("latency", {}), "rerank_ms": round(outcome.duration_ms, 1)},
        }

    async def check_context(state: RAGState) -> RAGState:
        chunks = state.get("reranked_documents", [])
        _emit(
            {
                "type": "sources",
                "chunks": [c.to_dict() for c in chunks],
                "rerank_mode": state.get("rerank_mode"),
                "cache_hit": False,
            }
        )
        if not chunks:
            _emit({"type": "token", "text": INSUFFICIENT_CONTEXT_MESSAGE})
            return {
                "insufficient_context": True,
                "answer": INSUFFICIENT_CONTEXT_MESSAGE,
                "citations": [],
            }
        return {"insufficient_context": False}

    async def generate(state: RAGState) -> RAGState:
        start = time.perf_counter()
        messages = build_messages(
            state["question"], [c.to_dict() for c in state["reranked_documents"]]
        )
        parts: list[str] = []
        async for delta in deps.generator.stream(messages):
            parts.append(delta)
            _emit({"type": "token", "text": delta})
        return {
            "answer": "".join(parts).strip(),
            "latency": {**state.get("latency", {}), "generation_ms": _ms(start)},
        }

    async def validate_output(state: RAGState) -> RAGState:
        answer = state.get("answer", "")
        if not answer:
            return {
                "answer": INSUFFICIENT_CONTEXT_MESSAGE,
                "insufficient_context": True,
                "citations": [],
                "errors": [*state.get("errors", []), "Model returned an empty answer"],
            }
        if is_insufficient(answer):
            return {"insufficient_context": True, "citations": []}
        answer, citations, errors = extract_citations(answer, state["reranked_documents"])
        if not citations:
            errors.append("Answer contained no valid citations.")
        return {
            "answer": answer,
            "citations": citations,
            "errors": [*state.get("errors", []), *errors],
        }

    async def finalize(state: RAGState) -> RAGState:
        latency = {**state.get("latency", {}), "total_ms": _ms(state["started_at"])}
        if (
            not state.get("cache_hit")
            and not state.get("insufficient_context")
            and state.get("citations")
            and state.get("rerank_mode") != "fallback_fusion"
            and state.get("use_cache", True)
        ):
            await deps.cache.set(
                state["question"],
                state.get("document_ids"),
                {
                    "answer": state["answer"],
                    "citations": state["citations"],
                    "insufficient_context": False,
                },
            )
        return {"latency": latency}

    def route_cache(state: RAGState) -> Literal["hit", "miss"]:
        return "hit" if state.get("cache_hit") else "miss"

    def route_context(state: RAGState) -> Literal["insufficient", "ok"]:
        return "insufficient" if state.get("insufficient_context") else "ok"

    graph = StateGraph(RAGState)
    graph.add_node("validate_request", validate_request)
    graph.add_node("check_cache", check_cache)
    graph.add_node("retrieve", retrieve)
    graph.add_node("fuse", fuse)
    graph.add_node("rerank", rerank)
    graph.add_node("check_context", check_context)
    graph.add_node("generate", generate)
    graph.add_node("validate_output", validate_output)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "validate_request")
    graph.add_edge("validate_request", "check_cache")
    graph.add_conditional_edges("check_cache", route_cache, {"hit": "finalize", "miss": "retrieve"})
    graph.add_edge("retrieve", "fuse")
    graph.add_edge("fuse", "rerank")
    graph.add_edge("rerank", "check_context")
    graph.add_conditional_edges(
        "check_context", route_context, {"insufficient": "finalize", "ok": "generate"}
    )
    graph.add_edge("generate", "validate_output")
    graph.add_edge("validate_output", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
