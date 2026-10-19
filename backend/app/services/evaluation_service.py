"""Evaluation run management (background jobs persisted in SQLite).

Runs execute as in-process asyncio tasks, one at a time. Status, per-case results and
aggregate metrics are persisted after every case, so progress survives page reloads but
NOT process restarts: runs left ``queued``/``running`` are marked ``interrupted`` on the
next startup. Use an external worker queue for durable, long evaluations.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailable
from app.evaluation.dataset import list_datasets, load_dataset
from app.evaluation.metrics import (
    SUPPORTED_METRICS,
    EvaluationScorer,
    RagasScorer,
    ragas_import_error,
    ragas_version,
)
from app.evaluation.runner import aggregate, case_failed, run_case
from app.rag.pipeline import RAGPipeline
from app.rag.vector_store import VectorStore
from app.schemas.evaluation import (
    DatasetInfo,
    EvaluationCaseResult,
    EvaluationPrerequisites,
    EvaluationResults,
    EvaluationRun,
    EvaluationRunRequest,
)
from app.storage.sqlite_store import AsyncStore, utcnow

logger = logging.getLogger(__name__)


class EvaluationService:
    def __init__(
        self,
        settings: Settings,
        store: AsyncStore,
        pipeline: RAGPipeline,
        vector_store: VectorStore,
        backend: EvaluationScorer | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.pipeline = pipeline
        self.vector_store = vector_store
        self._backend = backend  # injected in tests; RAGAS otherwise
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def list_datasets(self) -> list[DatasetInfo]:
        rows = await asyncio.to_thread(list_datasets, self.settings.evaluations_dir)
        return [DatasetInfo(**r) for r in rows]

    async def prerequisites(self) -> EvaluationPrerequisites:
        missing: list[str] = []
        if self._backend is None:
            if not self.settings.openai_configured:
                missing.append(
                    "OPENAI_API_KEY is not configured (needed for answers and LLM-judged metrics)."
                )
            err = await asyncio.to_thread(ragas_import_error)
            if err:
                missing.append(err)
        if not self.vector_store.initialized:
            missing.append("Vector store (Qdrant) is not available.")
        else:
            try:
                if await self.vector_store.count() == 0:
                    missing.append(
                        "No documents are indexed. For the sample dataset, upload "
                        "evaluations/sample_corpus/platform_guide.md first."
                    )
            except Exception:
                missing.append("Vector store (Qdrant) is not reachable.")
        if not await self.list_datasets():
            missing.append("No evaluation datasets found in the evaluations directory.")
        return EvaluationPrerequisites(
            ready=not missing,
            missing=missing,
            available_metrics=list(
                self._backend.metric_names if self._backend else SUPPORTED_METRICS
            ),
            ragas_version=ragas_version(),
        )

    async def start(self, req: EvaluationRunRequest) -> EvaluationRun:
        async with self._lock:
            pre = await self.prerequisites()
            if not pre.ready:
                raise ServiceUnavailable("Evaluation prerequisites not met", details=pre.missing)
            if (self._task and not self._task.done()) or await self.store.has_active_evaluation():
                raise ConflictError("An evaluation is already running")
            limit = min(req.limit or self.settings.max_eval_cases, self.settings.max_eval_cases)
            cases = await asyncio.to_thread(
                load_dataset, self.settings.evaluations_dir, req.dataset, limit
            )
            scorer = self._backend or RagasScorer(self.settings, req.metrics)
            evaluation_id = uuid.uuid4().hex
            await self.store.create_evaluation(
                {
                    "evaluation_id": evaluation_id,
                    "dataset": req.dataset,
                    "status": "queued",
                    "total_cases": len(cases),
                    "config": {
                        "llm_model": self.settings.openai_model,
                        "embedding_model": self.settings.openai_embedding_model,
                        "retrieval_top_k": self.settings.retrieval_top_k,
                        "rerank_top_k": self.settings.rerank_top_k,
                        "reranker": self.settings.reranker_model
                        if self.settings.reranker_enabled
                        else None,
                        "chunk_size": self.settings.chunk_size,
                        "chunk_overlap": self.settings.chunk_overlap,
                        "metrics": list(scorer.metric_names),
                        "ragas_version": ragas_version(),
                    },
                }
            )
            self._task = asyncio.create_task(self._execute(evaluation_id, cases, scorer))
        return await self.get(evaluation_id)

    async def _execute(
        self, evaluation_id: str, cases: list[Any], scorer: EvaluationScorer
    ) -> None:
        started = time.perf_counter()
        await self.store.update_evaluation(evaluation_id, status="running", started_at=utcnow())
        results: list[dict[str, Any]] = []
        completed = failed = 0
        try:
            for index, case in enumerate(cases):
                result = await run_case(index, case, self.pipeline, scorer)
                await self.store.save_evaluation_result(evaluation_id, result)
                results.append(result)
                if case_failed(result):
                    failed += 1
                else:
                    completed += 1
                await self.store.update_evaluation(
                    evaluation_id,
                    completed_cases=completed,
                    failed_cases=failed,
                    metrics=aggregate(results),
                )
            status = "completed" if completed > 0 else "failed"
            await self.store.update_evaluation(
                evaluation_id,
                status=status,
                error=None if completed else "All cases failed; see per-case errors",
                finished_at=utcnow(),
                duration_seconds=round(time.perf_counter() - started, 2),
            )
        except asyncio.CancelledError:
            await self.store.update_evaluation(
                evaluation_id,
                status="interrupted",
                error="Evaluation cancelled (shutdown)",
                finished_at=utcnow(),
                duration_seconds=round(time.perf_counter() - started, 2),
            )
            raise
        except Exception as exc:
            logger.exception("evaluation run failed")
            await self.store.update_evaluation(
                evaluation_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:500],
                finished_at=utcnow(),
                duration_seconds=round(time.perf_counter() - started, 2),
            )

    async def list(self, *, limit: int, offset: int) -> tuple[list[EvaluationRun], int]:
        rows, total = await self.store.list_evaluations(limit=limit, offset=offset)
        return [EvaluationRun(**r) for r in rows], total

    async def get(self, evaluation_id: str) -> EvaluationRun:
        row = await self.store.get_evaluation(evaluation_id)
        if row is None:
            raise NotFoundError(f"Evaluation '{evaluation_id}' not found")
        return EvaluationRun(**row)

    async def results(self, evaluation_id: str) -> EvaluationResults:
        await self.get(evaluation_id)
        rows = await self.store.list_evaluation_results(evaluation_id)
        return EvaluationResults(
            evaluation_id=evaluation_id, items=[EvaluationCaseResult(**r) for r in rows]
        )

    async def wait(self) -> None:
        """Await the current run (used by tests and scripts)."""
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    async def shutdown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
