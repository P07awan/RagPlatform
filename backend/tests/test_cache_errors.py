"""Redis cache behaviour (enabled/disabled/outage) and OpenAI error translation."""

from __future__ import annotations

import httpx
import openai
import pytest

from app.core.exceptions import (
    UpstreamAuthError,
    UpstreamError,
    UpstreamQuotaError,
    UpstreamRateLimited,
    UpstreamTimeout,
)
from app.rag.openai_client import raise_openai_error
from app.services.cache import AnswerCache
from tests.conftest import make_settings


class MemoryRedis:
    """Minimal async Redis stand-in implementing the commands AnswerCache uses."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttl[key] = ex

    async def incr(self, key):
        self.data[key] = str(int(self.data.get(key, "0")) + 1)
        return int(self.data[key])

    async def ping(self):
        return True

    async def aclose(self):
        pass


class DownRedis(MemoryRedis):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def get(self, key):
        self.calls += 1
        raise ConnectionError("redis down")

    async def ping(self):
        raise ConnectionError("redis down")


def cache_settings(tmp_path, **kw):
    return make_settings(tmp_path, enable_cache=True, redis_url="redis://localhost:6379/0", **kw)


async def test_cache_disabled_is_noop(tmp_path):
    cache = AnswerCache(make_settings(tmp_path))
    assert cache.enabled is False
    assert await cache.get("q", None) is None
    await cache.set("q", None, {"answer": "a"})
    assert await cache.ping() == "disabled"


async def test_cache_hit_after_set_with_normalized_key(tmp_path):
    redis = MemoryRedis()
    cache = AnswerCache(cache_settings(tmp_path, cache_ttl_seconds=120), client=redis)
    await cache.set("What is  BM25?", None, {"answer": "x", "citations": []})
    assert await cache.get("what is bm25?", None) == {"answer": "x", "citations": []}
    assert cache.hits == 1
    assert list(redis.ttl.values()) == [120]


async def test_cache_invalidated_by_corpus_version(tmp_path):
    cache = AnswerCache(cache_settings(tmp_path), client=MemoryRedis())
    await cache.set("q", None, {"answer": "old"})
    await cache.invalidate()  # e.g. a document was added or deleted
    assert await cache.get("q", None) is None
    assert cache.misses == 1


async def test_cache_key_depends_on_model_and_filters(tmp_path):
    a = AnswerCache(cache_settings(tmp_path, openai_model="gpt-4o-mini"))
    b = AnswerCache(cache_settings(tmp_path, openai_model="other-model"))
    assert a.build_key("q", None, "1") != b.build_key("q", None, "1")
    assert a.build_key("q", ["d1"], "1") != a.build_key("q", ["d2"], "1")
    assert a.build_key("q", ["d1", "d2"], "1") == a.build_key("q", ["d2", "d1"], "1")
    assert a.build_key("q", None, "1", scope="userA") != a.build_key("q", None, "1", scope="userB")


async def test_cache_outage_fails_open_with_cooldown(tmp_path):
    redis = DownRedis()
    cache = AnswerCache(cache_settings(tmp_path), client=redis)
    assert await cache.get("q", None) is None
    assert await cache.get("q", None) is None  # within cooldown: redis not called again
    assert redis.calls == 1 and cache.errors == 1
    await cache.set("q", None, {"answer": "a"})  # must not raise
    assert await cache.ping() == "down"


async def test_cached_answer_served_by_pipeline(
    tmp_path, embedder, generator, scorer, sample_corpus
):
    from app.main import create_app
    from tests.conftest import build_container

    settings = cache_settings(tmp_path)
    cache = AnswerCache(settings, client=MemoryRedis())
    app = create_app(settings, build_container(settings, embedder, generator, scorer, cache=cache))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        await c.post(
            "/api/v1/documents/upload",
            params={"wait": "true"},
            files=[("files", ("g.md", sample_corpus, "text/markdown"))],
        )
        first = (await c.post("/api/v1/chat", json={"question": "What is RRF?"})).json()
        second = (await c.post("/api/v1/chat", json={"question": "what is  rrf?"})).json()
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert second["answer"] == first["answer"] and second["citations"] == first["citations"]
    assert generator.calls == 1


async def test_insufficient_answers_not_cached(tmp_path, embedder, generator, scorer):
    from app.main import create_app
    from tests.conftest import build_container

    settings = cache_settings(tmp_path)
    redis = MemoryRedis()
    app = create_app(
        settings,
        build_container(
            settings, embedder, generator, scorer, cache=AnswerCache(settings, client=redis)
        ),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        await c.post("/api/v1/chat", json={"question": "nothing indexed"})
    assert not any(k.startswith("rag:answer:") for k in redis.data)


# ---------------------------------------------------------------------- OpenAI errors


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/x"))


def _status_error(cls, status: int, code: str | None = None):
    resp = _response(status)
    try:
        return cls("err", response=resp, body={"code": code} if code else None)
    except TypeError:  # SDK transports may use their own httpx fork
        import httpx2

        resp2 = httpx2.Response(
            status, request=httpx2.Request("POST", "https://api.openai.com/v1/x")
        )
        return cls("err", response=resp2, body={"code": code} if code else None)


@pytest.mark.parametrize(
    "exc, expected",
    [
        (lambda: _status_error(openai.AuthenticationError, 401), UpstreamAuthError),
        (
            lambda: _status_error(openai.RateLimitError, 429, "insufficient_quota"),
            UpstreamQuotaError,
        ),
        (
            lambda: _status_error(openai.RateLimitError, 429, "rate_limit_exceeded"),
            UpstreamRateLimited,
        ),
        (lambda: _status_error(openai.NotFoundError, 404), UpstreamError),
        (lambda: _status_error(openai.InternalServerError, 500), UpstreamError),
    ],
)
def test_openai_errors_translated(exc, expected):
    with pytest.raises(expected):
        raise_openai_error(exc(), "embedding")


def test_openai_timeout_translated():
    try:
        err = openai.APITimeoutError(request=httpx.Request("POST", "https://x"))
    except TypeError:
        import httpx2

        err = openai.APITimeoutError(request=httpx2.Request("POST", "https://x"))
    with pytest.raises(UpstreamTimeout):
        raise_openai_error(err, "generation")


def test_quota_error_message_is_actionable():
    with pytest.raises(UpstreamQuotaError, match="billing"):
        raise_openai_error(
            _status_error(openai.RateLimitError, 429, "insufficient_quota"), "embedding"
        )
