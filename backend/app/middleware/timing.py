"""Request timing + access logging (pure ASGI so streaming is not buffered)."""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.access")


class TimingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                elapsed = (time.perf_counter() - start) * 1000
                headers = list(message.get("headers", []))
                # Time-to-headers; for streams the full duration is logged below.
                headers.append((b"x-response-time-ms", f"{elapsed:.1f}".encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "request completed",
                extra={
                    "method": scope.get("method"),
                    "route": scope.get("path"),
                    "status": status["code"],
                    "duration_ms": duration_ms,
                },
            )
