"""Cross-encoder reranking.

Default model: ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (~22M parameters, ~90 MB on disk,
roughly 200–400 MB RSS on CPU including PyTorch overhead). It is downloaded once to the
Hugging Face cache on first load and kept in memory for the life of the process.

Failure policy (``RERANKER_FALLBACK``):
* ``error``  – requests that need reranking fail with a clear 503.
* ``fusion`` – results keep their fused RRF order and responses report
  ``rerank_mode="fallback_fusion"`` so it is never silently presented as reranked.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.exceptions import RerankerUnavailable
from app.rag.hybrid_retriever import Candidate

logger = logging.getLogger(__name__)

RerankMode = Literal["cross_encoder", "disabled", "fallback_fusion"]


class PairScorer(Protocol):
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]: ...


@dataclass
class RerankOutcome:
    candidates: list[Candidate]
    mode: RerankMode
    duration_ms: float

    @property
    def applied(self) -> bool:
        return self.mode == "cross_encoder"


class SentenceTransformerScorer:
    def __init__(self, model_name: str, max_length: int = 512) -> None:
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name, max_length=max_length, device="cpu")

    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        scores = self._model.predict(list(pairs), batch_size=16, show_progress_bar=False)
        return [float(s) for s in scores]


class CrossEncoderReranker:
    def __init__(
        self,
        model_name: str,
        *,
        enabled: bool = True,
        fallback: Literal["error", "fusion"] = "error",
        min_score: float | None = None,
        scorer: PairScorer | None = None,
    ) -> None:
        self.model_name = model_name
        self.enabled = enabled
        self.fallback = fallback
        self.min_score = min_score
        self._scorer = scorer
        self._load_error: str | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        if self._scorer is not None:
            return "loaded"
        if self._load_error:
            return "failed"
        return "not_loaded"

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> PairScorer | None:
        """Load the model once (thread-safe). Returns None on failure."""
        if self._scorer is not None or not self.enabled:
            return self._scorer
        with self._lock:
            if self._scorer is None and self._load_error is None:
                start = time.perf_counter()
                try:
                    self._scorer = SentenceTransformerScorer(self.model_name)
                    logger.info(
                        "reranker loaded",
                        extra={
                            "model": self.model_name,
                            "load_ms": round((time.perf_counter() - start) * 1000),
                        },
                    )
                except Exception as exc:  # network, disk, incompatible weights ...
                    self._load_error = f"{type(exc).__name__}: {exc}"
                    logger.error("reranker failed to load", extra={"error": self._load_error})
        return self._scorer

    def _fallback(self, candidates: list[Candidate], top_n: int, reason: str) -> RerankOutcome:
        if self.fallback == "fusion":
            logger.warning("rerank fallback to fusion order", extra={"reason": reason})
            return RerankOutcome(candidates[:top_n], "fallback_fusion", 0.0)
        raise RerankerUnavailable(f"Reranker unavailable: {reason}")

    def rerank_sync(self, query: str, candidates: list[Candidate], top_n: int) -> RerankOutcome:
        if not candidates:
            mode: RerankMode = "cross_encoder" if self.enabled else "disabled"
            return RerankOutcome([], mode, 0.0)
        if not self.enabled:
            return RerankOutcome(candidates[:top_n], "disabled", 0.0)
        scorer = self.load()
        if scorer is None:
            return self._fallback(candidates, top_n, self._load_error or "model not loaded")
        start = time.perf_counter()
        try:
            scores = scorer.predict([(query, c.content) for c in candidates])
        except Exception as exc:
            logger.exception("reranker inference failed")
            return self._fallback(candidates, top_n, f"inference failed: {type(exc).__name__}")
        for cand, score in zip(candidates, scores, strict=True):
            cand.rerank_score = float(score)
        ranked = sorted(candidates, key=lambda c: (-(c.rerank_score or 0.0), -c.fused_score))
        if self.min_score is not None:
            ranked = [c for c in ranked if (c.rerank_score or 0.0) >= self.min_score]
        return RerankOutcome(ranked[:top_n], "cross_encoder", (time.perf_counter() - start) * 1000)

    async def rerank(self, query: str, candidates: list[Candidate], top_n: int) -> RerankOutcome:
        # CPU-bound inference runs in a worker thread so the event loop stays responsive.
        return await asyncio.to_thread(self.rerank_sync, query, candidates, top_n)
