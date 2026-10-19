"""Chat orchestration: runs the RAG graph and shapes responses / SSE events.

SSE event contract (``POST /api/v1/chat/stream``)::

    event: start     data: {"request_id": str, "session_id": str}
    event: sources   data: {"chunks": [RetrievedChunk], "rerank_mode": str|null, "cache_hit": bool}
    event: token     data: {"text": str}                       (0..n times)
    event: metadata  data: ChatResponse                          (validated answer + citations)
    event: error     data: {"code": str, "message": str, "request_id": str}
    event: done      data: {}

Every frame is ``event: <name>\\ndata: <single-line JSON>\\n\\n``. ``done`` is always last.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.logging import request_id_ctx
from app.rag.graph import RAGState
from app.rag.pipeline import RAGPipeline
from app.schemas.chat import ChatRequest, ChatResponse
from app.storage.sqlite_store import AsyncStore

logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict[str, Any]) -> str:
    # json.dumps never emits raw newlines, so the payload is always a single data line.
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


class ChatService:
    def __init__(self, settings: Settings, pipeline: RAGPipeline, store: AsyncStore) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self.store = store

    def build_response(self, state: RAGState, include_retrieval: bool) -> ChatResponse:
        retrieval = None
        if include_retrieval and not state.get("cache_hit"):
            scores = state.get("retrieval_scores", {})
            retrieval = {
                "dense_candidates": scores.get("dense_candidates", 0),
                "bm25_candidates": scores.get("bm25_candidates", 0),
                "fused_candidates": scores.get("fused_candidates", 0),
                "reranked": state.get("rerank_mode") == "cross_encoder",
                "rerank_mode": state.get("rerank_mode") or "n/a",
                "chunks": [c.to_dict() for c in state.get("reranked_documents", [])],
            }
        latency = state.get("latency", {})
        return ChatResponse(
            answer=state.get("answer", ""),
            citations=state.get("citations", []),
            session_id=state["session_id"],
            request_id=request_id_ctx.get(),
            insufficient_context=bool(state.get("insufficient_context")),
            cache_hit=bool(state.get("cache_hit")),
            model=self.pipeline.generator.model,
            latency=latency,
            retrieval=retrieval,
        )

    async def _record(self, req: ChatRequest, state: RAGState | None, status: str) -> None:
        try:
            await self.store.record_chat(
                {
                    "session_id": (state or {}).get("session_id") or req.session_id,
                    "question_preview": req.question[:200],
                    "latency_ms": (state or {}).get("latency", {}).get("total_ms"),
                    "citation_count": len((state or {}).get("citations", [])),
                    "cache_hit": int(bool((state or {}).get("cache_hit"))),
                    "insufficient_context": int(bool((state or {}).get("insufficient_context"))),
                    "status": status,
                }
            )
        except Exception:  # activity logging must never break chat
            logger.exception("failed to record chat activity")

    async def chat(self, req: ChatRequest) -> ChatResponse:
        state = self.pipeline.initial_state(
            req.question, session_id=req.session_id, document_ids=req.document_ids
        )
        try:
            final = await self.pipeline.run(state)
        except AppError as exc:
            await self._record(req, None, exc.code)
            raise
        await self._record(req, final, "ok")
        return self.build_response(final, req.include_retrieval)

    async def stream(
        self, req: ChatRequest, is_disconnected: Callable[[], Awaitable[bool]]
    ) -> AsyncIterator[str]:
        state = self.pipeline.initial_state(
            req.question, session_id=req.session_id, document_ids=req.document_ids
        )
        yield sse_event(
            "start", {"request_id": request_id_ctx.get(), "session_id": state["session_id"]}
        )
        final: RAGState | None = None
        status = "ok"
        events = self.pipeline.stream(state)
        try:
            async for kind, payload in events:
                if await is_disconnected():
                    status = "client_disconnected"
                    logger.info("client disconnected; stopping generation")
                    return
                if kind == "event":
                    event_type = payload.pop("type")
                    yield sse_event(event_type, payload)
                else:
                    final = payload
            if final is not None:
                response = self.build_response(final, req.include_retrieval)
                yield sse_event("metadata", response.model_dump(mode="json"))
        except AppError as exc:
            status = exc.code
            logger.warning("stream failed", extra={"error_code": exc.code, "error": exc.message})
            yield sse_event(
                "error",
                {"code": exc.code, "message": exc.message, "request_id": request_id_ctx.get()},
            )
        except Exception:
            status = "internal_error"
            logger.exception("unexpected streaming error")
            yield sse_event(
                "error",
                {
                    "code": "internal_error",
                    "message": "An unexpected error occurred",
                    "request_id": request_id_ctx.get(),
                },
            )
        finally:
            await events.aclose()  # cancels in-flight graph work (e.g. the OpenAI stream)
            await self._record(req, final, status)
        yield sse_event("done", {})
