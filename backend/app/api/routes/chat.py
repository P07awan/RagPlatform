from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_container
from app.core.container import AppContainer
from app.core.security import rate_limit
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_model=ChatResponse,
    dependencies=[Depends(rate_limit)],
    summary="Ask a question (non-streaming)",
)
async def chat(req: ChatRequest, c: AppContainer = Depends(get_container)) -> ChatResponse:
    return await c.chat.chat(req)


@router.post(
    "/stream",
    dependencies=[Depends(rate_limit)],
    summary="Ask a question and stream the answer (Server-Sent Events)",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "SSE stream: start, sources, token*, metadata|error, done",
        }
    },
)
async def chat_stream(
    req: ChatRequest, request: Request, c: AppContainer = Depends(get_container)
) -> StreamingResponse:
    return StreamingResponse(
        c.chat.stream(req, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
