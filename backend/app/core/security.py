"""API-key authentication and a lightweight in-process rate limiter.

This is a *single-user portfolio* auth model: one shared application key sent in the
``X-API-Key`` header. A multi-user production system needs real user identity
(OIDC/OAuth, per-user document ACLs, key rotation) – see the README security section.
"""

from __future__ import annotations

import hmac
import time
from collections import OrderedDict
from threading import Lock

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from app.core.exceptions import AppError, RateLimited

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


def verify_api_key(request: Request, provided: str | None = Depends(api_key_header)) -> None:
    settings = request.app.state.container.settings
    if not settings.auth_enabled:
        return
    if not provided:
        raise Unauthorized("Missing X-API-Key header")
    expected = settings.api_key.get_secret_value()
    # Constant-time comparison avoids leaking key prefixes through timing.
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        raise Unauthorized("Invalid API key")


class SlidingWindowRateLimiter:
    """Per-client fixed-window counter with a bounded number of tracked clients.

    In-process only: with several workers/instances each enforces its own limit.
    Use a shared store (e.g. Redis) or an API gateway for a real deployment.
    """

    def __init__(self, limit_per_minute: int, max_clients: int = 10_000) -> None:
        self.limit = limit_per_minute
        self.max_clients = max_clients
        self._windows: OrderedDict[str, tuple[int, int]] = OrderedDict()
        self._lock = Lock()

    def check(self, client: str) -> None:
        if self.limit <= 0:
            return
        window = int(time.time() // 60)
        with self._lock:
            start, count = self._windows.pop(client, (window, 0))
            if start != window:
                start, count = window, 0
            count += 1
            self._windows[client] = (start, count)
            while len(self._windows) > self.max_clients:
                self._windows.popitem(last=False)
        if count > self.limit:
            raise RateLimited(f"Rate limit exceeded ({self.limit} requests/minute)")


def rate_limit(request: Request) -> None:
    limiter: SlidingWindowRateLimiter = request.app.state.container.rate_limiter
    client = request.client.host if request.client else "unknown"
    limiter.check(client)
