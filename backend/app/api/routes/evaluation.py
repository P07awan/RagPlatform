from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_container
from app.core.container import AppContainer
from app.core.security import rate_limit
from app.schemas.evaluation import (
    DatasetInfo,
    EvaluationList,
    EvaluationPrerequisites,
    EvaluationResults,
    EvaluationRun,
    EvaluationRunRequest,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get("/datasets", response_model=list[DatasetInfo], summary="Available evaluation datasets")
async def datasets(c: AppContainer = Depends(get_container)) -> list[DatasetInfo]:
    return await c.evaluations.list_datasets()


@router.get(
    "/prerequisites",
    response_model=EvaluationPrerequisites,
    summary="What is needed before an evaluation can run",
)
async def prerequisites(c: AppContainer = Depends(get_container)) -> EvaluationPrerequisites:
    return await c.evaluations.prerequisites()


@router.post(
    "/run",
    response_model=EvaluationRun,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit)],
    summary="Start a background RAGAS evaluation run",
)
async def run_evaluation(
    req: EvaluationRunRequest, c: AppContainer = Depends(get_container)
) -> EvaluationRun:
    return await c.evaluations.start(req)


@router.get("", response_model=EvaluationList, summary="List evaluation runs")
async def list_evaluations(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    c: AppContainer = Depends(get_container),
) -> EvaluationList:
    items, total = await c.evaluations.list(limit=limit, offset=offset)
    return EvaluationList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{evaluation_id}", response_model=EvaluationRun, summary="Get one evaluation run")
async def get_evaluation(
    evaluation_id: str, c: AppContainer = Depends(get_container)
) -> EvaluationRun:
    return await c.evaluations.get(evaluation_id)


@router.get(
    "/{evaluation_id}/results", response_model=EvaluationResults, summary="Per-case results"
)
async def get_results(
    evaluation_id: str, c: AppContainer = Depends(get_container)
) -> EvaluationResults:
    return await c.evaluations.results(evaluation_id)
