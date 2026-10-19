from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvaluationStatus = Literal["queued", "running", "completed", "failed", "interrupted"]


class EvaluationRunRequest(BaseModel):
    dataset: str = Field(default="sample_dataset", pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    limit: int | None = Field(
        default=None, ge=1, le=500, description="Evaluate only the first N cases (cost control)."
    )
    metrics: list[str] | None = Field(
        default=None, description="Subset of metrics; defaults to all supported."
    )


class EvaluationRun(BaseModel):
    evaluation_id: str
    dataset: str
    status: EvaluationStatus
    total_cases: int
    completed_cases: int
    failed_cases: int
    metrics: dict[str, float | None]
    config: dict[str, object]
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None


class EvaluationList(BaseModel):
    items: list[EvaluationRun]
    total: int
    limit: int
    offset: int


class EvaluationCaseResult(BaseModel):
    case_index: int
    case_id: str | None = None
    question: str
    reference_answer: str | None = None
    generated_answer: str | None = None
    retrieved_contexts: list[str]
    reference_contexts: list[str]
    scores: dict[str, float | None]
    error: str | None = None
    latency_ms: float | None = None


class EvaluationResults(BaseModel):
    evaluation_id: str
    items: list[EvaluationCaseResult]


class DatasetInfo(BaseModel):
    name: str
    cases: int
    description: str | None = None


class EvaluationPrerequisites(BaseModel):
    ready: bool
    missing: list[str]
    available_metrics: list[str]
    ragas_version: str | None = None
