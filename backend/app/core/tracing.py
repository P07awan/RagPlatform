"""Optional LangSmith tracing.

LangChain/LangGraph and the ``langsmith`` SDK read their configuration from environment
variables (``LANGSMITH_TRACING``, ``LANGSMITH_API_KEY``, ``LANGSMITH_PROJECT``,
``LANGSMITH_ENDPOINT``). Pydantic Settings loads ``.env`` without exporting it, so we
export the validated values here. When tracing is disabled we force it off so a stray
shell variable cannot enable it silently.

Traced: the LangGraph run (every node as a child span) and OpenAI calls (via
``langsmith.wrappers.wrap_openai``). Set ``LANGSMITH_HIDE_CONTENT=true`` to redact
inputs/outputs (questions, document text, answers) from traces.
"""

from __future__ import annotations

import logging
import os

from app.core.config import Settings

logger = logging.getLogger(__name__)


def configure_tracing(settings: Settings) -> bool:
    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        return False
    assert settings.langsmith_api_key is not None  # guaranteed by Settings validation
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    if settings.langsmith_hide_content:
        os.environ["LANGSMITH_HIDE_INPUTS"] = "true"
        os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true"
    logger.info("langsmith tracing enabled", extra={"project": settings.langsmith_project})
    return True
