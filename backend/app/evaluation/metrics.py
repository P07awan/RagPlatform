"""RAGAS metric scoring (ragas 0.4.x "collections" API).

Verified against ragas 0.4.3:
* ``ragas.llms.base.llm_factory(model, client=AsyncOpenAI)`` → instructor-based judge LLM
* ``ragas.embeddings.OpenAIEmbeddings(client=..., model=...)``
* ``ragas.metrics.collections.{Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall}``
  each exposing ``await metric.ascore(...) -> MetricResult`` (``.value`` is a float, NaN when
  the metric is undefined for the sample).

Cost note: every LLM-judged metric calls the OpenAI API. Per case roughly: faithfulness 2
calls, answer relevancy 3 calls + embeddings, context precision 1 call per retrieved context,
context recall 1 call.

An extra, non-RAGAS check ``abstention`` is computed (no API cost) for cases marked
``expect_insufficient``: 1.0 if the pipeline declined to answer, else 0.0.
"""

from __future__ import annotations

import asyncio
import logging
import math
from importlib import metadata
from typing import Any, Protocol

from app.core.config import Settings
from app.evaluation.dataset import EvalCase

logger = logging.getLogger(__name__)

SUPPORTED_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
METRIC_TIMEOUT_SECONDS = 120


def ragas_version() -> str | None:
    try:
        return metadata.version("ragas")
    except metadata.PackageNotFoundError:
        return None


def ragas_import_error() -> str | None:
    try:
        import ragas.metrics.collections  # noqa: F401
    except Exception as exc:  # ImportError or incompatible transitive deps
        return f"RAGAS cannot be imported: {type(exc).__name__}: {exc}"
    return None


class EvaluationScorer(Protocol):
    metric_names: tuple[str, ...]

    async def score(
        self, case: EvalCase, answer: str, contexts: list[str], insufficient: bool
    ) -> tuple[dict[str, float | None], list[str]]: ...


def _clean(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, 4)


class RagasScorer:
    def __init__(self, settings: Settings, metric_names: list[str] | None = None) -> None:
        from openai import AsyncOpenAI
        from ragas.embeddings import OpenAIEmbeddings
        from ragas.llms.base import llm_factory
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )

        names = tuple(metric_names or SUPPORTED_METRICS)
        unknown = set(names) - set(SUPPORTED_METRICS)
        if unknown:
            raise ValueError(f"Unsupported metrics: {sorted(unknown)}")
        assert settings.openai_api_key is not None
        client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        llm = llm_factory(settings.openai_model, client=client)
        self.metric_names = names
        self._metrics: dict[str, Any] = {}
        if "faithfulness" in names:
            self._metrics["faithfulness"] = Faithfulness(llm=llm)
        if "answer_relevancy" in names:
            embeddings = OpenAIEmbeddings(client=client, model=settings.openai_embedding_model)
            self._metrics["answer_relevancy"] = AnswerRelevancy(llm=llm, embeddings=embeddings)
        if "context_precision" in names:
            self._metrics["context_precision"] = ContextPrecision(llm=llm)
        if "context_recall" in names:
            self._metrics["context_recall"] = ContextRecall(llm=llm)

    def _calls(self, case: EvalCase, answer: str, contexts: list[str]) -> dict[str, Any]:
        calls: dict[str, Any] = {}
        m = self._metrics
        if "faithfulness" in m and contexts:
            calls["faithfulness"] = m["faithfulness"].ascore(
                user_input=case.question, response=answer, retrieved_contexts=contexts
            )
        if "answer_relevancy" in m:
            calls["answer_relevancy"] = m["answer_relevancy"].ascore(
                user_input=case.question, response=answer
            )
        if case.reference_answer and contexts:
            if "context_precision" in m:
                calls["context_precision"] = m["context_precision"].ascore(
                    user_input=case.question,
                    reference=case.reference_answer,
                    retrieved_contexts=contexts,
                )
            if "context_recall" in m:
                calls["context_recall"] = m["context_recall"].ascore(
                    user_input=case.question,
                    retrieved_contexts=contexts,
                    reference=case.reference_answer,
                )
        return calls

    async def score(
        self, case: EvalCase, answer: str, contexts: list[str], insufficient: bool
    ) -> tuple[dict[str, float | None], list[str]]:
        scores: dict[str, float | None] = {}
        errors: list[str] = []
        if case.expect_insufficient:
            # Answer-quality metrics are meaningless for questions the corpus cannot answer.
            scores["abstention"] = 1.0 if insufficient else 0.0
            return scores, errors
        if not answer:
            return scores, ["No answer generated"]
        calls = self._calls(case, answer, contexts)
        names = list(calls)
        results = await asyncio.gather(
            *(asyncio.wait_for(c, METRIC_TIMEOUT_SECONDS) for c in calls.values()),
            return_exceptions=True,
        )
        for name, result in zip(names, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("metric failed", extra={"metric": name, "error": repr(result)[:300]})
                errors.append(f"{name}: {type(result).__name__}")
                scores[name] = None
            else:
                scores[name] = _clean(getattr(result, "value", result))
        return scores, errors
