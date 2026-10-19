from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.core.exceptions import RateLimited
from app.core.logging import JsonFormatter, redact
from app.core.security import SlidingWindowRateLimiter
from tests.conftest import make_settings


def test_defaults_are_valid(tmp_path):
    s = make_settings(
        tmp_path, openai_embedding_model="text-embedding-3-small", embedding_dimensions=None
    )
    assert s.vector_size == 1536
    assert not s.auth_enabled
    assert s.max_upload_bytes == 20 * 1024 * 1024


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"chunk_size": 200, "chunk_overlap": 200}, "CHUNK_OVERLAP"),
        ({"retrieval_top_k": 2, "rerank_top_k": 3}, "RERANK_TOP_K"),
        ({"enable_cache": True, "redis_url": None}, "REDIS_URL"),
        ({"langsmith_tracing": True, "langsmith_api_key": None}, "LANGSMITH_API_KEY"),
        ({"cors_origins": "*"}, "Wildcard"),
        (
            {"openai_embedding_model": "mystery-model", "embedding_dimensions": None},
            "EMBEDDING_DIMENSIONS",
        ),
        ({"log_level": "LOUD"}, "LOG_LEVEL"),
    ],
)
def test_invalid_configuration_fails_clearly(tmp_path, overrides, message):
    with pytest.raises(ValidationError) as exc:
        make_settings(tmp_path, **overrides)
    assert message in str(exc.value)


def test_production_requires_secrets(tmp_path):
    with pytest.raises(ValidationError) as exc:
        make_settings(tmp_path, environment="production", qdrant_path=None)
    assert "OPENAI_API_KEY" in str(exc.value) and "API_KEY" in str(exc.value)


def test_production_rejects_embedded_qdrant(tmp_path):
    with pytest.raises(ValidationError, match="QDRANT_PATH"):
        make_settings(tmp_path, environment="production", openai_api_key="sk-x", api_key="k")


def test_cors_origins_parsed_from_comma_string(tmp_path):
    s = make_settings(tmp_path, cors_origins="http://a.com/, https://b.com")
    assert s.cors_origins == ["http://a.com", "https://b.com"]


def test_empty_strings_become_none(tmp_path):
    s = make_settings(tmp_path, openai_api_key="", api_key="  ", redis_url="")
    assert s.openai_api_key is None and s.api_key is None and s.redis_url is None


def test_secrets_are_not_in_repr(tmp_path):
    s = make_settings(
        tmp_path, openai_api_key="sk-supersecretvalue1234567890", api_key="app-key-123"
    )
    assert "supersecret" not in repr(s)
    assert "app-key-123" not in repr(s)


def test_redact_masks_keys_and_headers():
    text = 'calling with sk-abcdefghijklmnopqrstuvwxyz and X-API-Key: hunter2 api_key="abc"'
    out = redact(text)
    assert "sk-abcdef" not in out
    assert "hunter2" not in out
    assert 'abc"' not in out.replace("[REDACTED]", "")


def test_json_formatter_redacts_messages():
    record = logging.makeLogRecord(
        {"msg": "key sk-abcdefghijklmnopqrstuvwxyz leaked", "levelname": "INFO", "name": "t"}
    )
    assert "sk-abcdef" not in JsonFormatter().format(record)


def test_rate_limiter_blocks_after_limit():
    limiter = SlidingWindowRateLimiter(limit_per_minute=2)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(RateLimited):
        limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # other clients unaffected


def test_rate_limiter_bounded_memory():
    limiter = SlidingWindowRateLimiter(limit_per_minute=5, max_clients=10)
    for i in range(50):
        limiter.check(f"client-{i}")
    assert len(limiter._windows) == 10


def test_rate_limiter_disabled_when_zero():
    limiter = SlidingWindowRateLimiter(limit_per_minute=0)
    for _ in range(100):
        limiter.check("x")
