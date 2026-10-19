"""Evaluation runner: answers each case with the real RAG pipeline, then scores it."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.exceptions import AppError
from app.evaluation.dataset import EvalCase
from app.evaluation.metrics import EvaluationScorer
from app.rag.pipeline import RAGPipeline

logger = logging.getLogger(__name__)

ResultSink = Callable[[dict[str, Any]], Awaitable[None]]


async def run_case(
    index: int, case: EvalCase, pipeline: RAGPipeline, scorer: EvaluationScorer
) -> dict[str, Any]:
    start = time.perf_counter()
    result: dict[str, Any] = {
        "case_index": index,
        "case_id": case.id,
        "question": case.question,
        "reference_answer": case.reference_answer,
        "reference_contexts": case.reference_contexts,
        "generated_answer": None,
        "retrieved_contexts": [],
        "scores": {},
        "error": None,
    }
    try:
        state = await pipeline.run(pipeline.initial_state(case.question, use_cache=False))
        answer = state.get("answer", "")
        contexts = [c.content for c in state.get("reranked_documents", [])]
        result["generated_answer"] = answer
        result["retrieved_contexts"] = contexts
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        scores, errors = await scorer.score(
            case, answer, contexts, bool(state.get("insufficient_context"))
        )
        result["scores"] = scores
        if errors:
            result["error"] = "; ".join(errors)
    except AppError as exc:
        result["error"] = f"{exc.code}: {exc.message}"
    except Exception as exc:  # keep the run going; record the failure for this case
        logger.exception("evaluation case failed", extra={"case_index": index})
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    result.setdefault("latency_ms", round((time.perf_counter() - start) * 1000, 1))
    return result


def aggregate(results: list[dict[str, Any]]) -> dict[str, float | None]:
    """Mean of each metric over cases where it was computed (None/NaN excluded)."""
    sums: dict[str, list[float]] = {}
    for r in results:
        for name, value in r.get("scores", {}).items():
            if value is not None:
                sums.setdefault(name, []).append(float(value))
    return {name: round(sum(v) / len(v), 4) for name, v in sorted(sums.items()) if v}


def case_failed(result: dict[str, Any]) -> bool:
    """A case fails if no answer was produced or no metric could be computed."""
    if result.get("generated_answer") is None:
        return True
    scores = result.get("scores", {})
    return not scores or all(v is None for v in scores.values())
