"""Shared OpenAI client factory and error translation.

Retries: the OpenAI SDK retries connection errors, 408/409/429 and 5xx responses with
exponential backoff, bounded by ``OPENAI_MAX_RETRIES``. Authentication and validation
errors are not retried. We never fall back to a different model on failure.
"""

from __future__ import annotations

from typing import NoReturn

import openai
from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationError,
    UpstreamAuthError,
    UpstreamError,
    UpstreamQuotaError,
    UpstreamRateLimited,
    UpstreamTimeout,
)


def build_openai_client(settings: Settings) -> AsyncOpenAI:
    if settings.openai_api_key is None:
        raise ConfigurationError("OPENAI_API_KEY is not configured on the server")
    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )
    if settings.langsmith_tracing:
        from langsmith.wrappers import wrap_openai

        client = wrap_openai(client)
    return client


def raise_openai_error(exc: Exception, operation: str) -> NoReturn:
    """Translate SDK exceptions into client-safe application errors."""
    if isinstance(exc, openai.AuthenticationError):
        raise UpstreamAuthError(
            f"OpenAI rejected the API key during {operation}. Check OPENAI_API_KEY."
        ) from exc
    if isinstance(exc, openai.PermissionDeniedError):
        raise UpstreamAuthError(
            f"OpenAI denied access during {operation} (model or project permissions)."
        ) from exc
    if isinstance(exc, openai.RateLimitError):
        code = getattr(exc, "code", None)
        if code == "insufficient_quota":
            raise UpstreamQuotaError(
                "OpenAI quota exhausted or billing not configured for this API key."
            ) from exc
        raise UpstreamRateLimited(
            f"OpenAI rate limit hit during {operation}; retry later."
        ) from exc
    if isinstance(exc, openai.APITimeoutError):
        raise UpstreamTimeout(f"OpenAI request timed out during {operation}.") from exc
    if isinstance(exc, openai.APIConnectionError):
        raise UpstreamError(f"Could not reach OpenAI during {operation}.") from exc
    if isinstance(exc, openai.NotFoundError):
        raise UpstreamError(
            f"OpenAI reported a missing resource during {operation}; verify the configured "
            "model identifiers are available to your account."
        ) from exc
    if isinstance(exc, openai.BadRequestError):
        raise UpstreamError(f"OpenAI rejected the {operation} request: {exc.message}") from exc
    if isinstance(exc, openai.APIStatusError):
        raise UpstreamError(f"OpenAI returned HTTP {exc.status_code} during {operation}.") from exc
    raise UpstreamError(f"Unexpected error during {operation}.") from exc
