from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import AppContainer
from app.core.security import rate_limit
from app.schemas.retrieval import SearchRequest, SearchResponse

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(rate_limit)],
    summary="Hybrid search + rerank (no answer generation)",
)
async def search(req: SearchRequest, c: AppContainer = Depends(get_container)) -> SearchResponse:
    result = await c.pipeline.search(
        req.query.strip(),
        top_k=req.top_k,
        rerank_top_k=req.rerank_top_k,
        rerank=req.rerank,
        document_ids=req.document_ids,
    )
    return SearchResponse(**result)
