"""Startup, health, readiness, authentication, validation and error-format tests."""

from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from tests.conftest import build_container, make_settings


async def test_health_reports_components(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["components"]) >= {"qdrant", "openai", "reranker", "cache", "tracing"}
    assert body["components"]["cache"]["status"] == "disabled"
    assert "x-request-id" in r.headers


async def test_ready_when_dependencies_available(client):
    r = await client.get("/api/v1/ready")
    assert r.status_code == 200
    assert r.json()["ready"] is True


async def test_ready_not_ready_without_openai(tmp_path, embedder, generator, scorer):
    from app.rag.pipeline import UnconfiguredEmbedder

    settings = make_settings(tmp_path)
    container = build_container(settings, embedder, generator, scorer)
    container.embedder = UnconfiguredEmbedder("x", 64)  # simulate missing key
    app = create_app(settings, container)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        r = await c.get("/api/v1/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["openai"]["status"] == "not_configured"


async def test_request_id_is_propagated(client):
    r = await client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


async def test_invalid_request_id_is_replaced(client):
    r = await client.get("/api/v1/health", headers={"X-Request-ID": "bad id with spaces!"})
    assert r.headers["x-request-id"] != "bad id with spaces!"


async def test_openapi_docs_available(client):
    r = await client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for p in [
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/documents/upload",
        "/api/v1/documents",
        "/api/v1/documents/{document_id}",
        "/api/v1/chat",
        "/api/v1/chat/stream",
        "/api/v1/retrieval/search",
        "/api/v1/evaluations/run",
        "/api/v1/evaluations",
        "/api/v1/evaluations/{evaluation_id}",
        "/api/v1/evaluations/{evaluation_id}/results",
    ]:
        assert p in paths, p


async def test_config_status_never_contains_secrets(tmp_path, embedder, generator, scorer):
    settings = make_settings(
        tmp_path, api_key="topsecret-app-key", openai_api_key="sk-live-should-not-leak-123456"
    )
    app = create_app(settings, build_container(settings, embedder, generator, scorer))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        r = await c.get("/api/v1/config", headers={"X-API-Key": "topsecret-app-key"})
    assert r.status_code == 200
    text = r.text
    assert "topsecret" not in text and "sk-live" not in text
    assert r.json()["auth_enabled"] is True


class TestAuthentication:
    @pytest.fixture
    def settings(self, tmp_path):
        return make_settings(tmp_path, api_key="correct-key")

    async def test_health_is_public(self, client):
        assert (await client.get("/api/v1/health")).status_code == 200

    async def test_missing_key_rejected(self, client):
        r = await client.get("/api/v1/documents")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"

    async def test_wrong_key_rejected(self, client):
        r = await client.get("/api/v1/documents", headers={"X-API-Key": "wrong"})
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Invalid API key"

    async def test_valid_key_accepted(self, client):
        r = await client.get("/api/v1/documents", headers={"X-API-Key": "correct-key"})
        assert r.status_code == 200

    async def test_chat_protected(self, client):
        r = await client.post("/api/v1/chat", json={"question": "hi"})
        assert r.status_code == 401


async def test_validation_errors_use_consistent_format(client):
    r = await client.post("/api/v1/chat", json={"question": "   "})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["request_id"]
    assert isinstance(err["details"], list)


async def test_invalid_session_id_rejected(client):
    r = await client.post("/api/v1/chat", json={"question": "ok", "session_id": "../etc/passwd"})
    assert r.status_code == 422


async def test_unknown_document_returns_404(client):
    r = await client.get("/api/v1/documents/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_unknown_route_returns_json_404(client):
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert "error" in r.json()


async def test_pagination_validation(client):
    r = await client.get("/api/v1/documents", params={"limit": 1000})
    assert r.status_code == 422


async def test_unhandled_errors_do_not_leak_stack_traces(client, container, monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(container.store.sync, "list_documents", boom)
    # Starlette re-raises after sending the 500 so servers can log it; read the response.
    transport = httpx.ASGITransport(app=client._transport.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
        r = await raw.get("/api/v1/documents")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text
    assert r.json()["error"]["code"] == "internal_error"


async def test_cors_allows_configured_origin_only(client):
    ok = await client.options(
        "/api/v1/documents",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = await client.options(
        "/api/v1/documents",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert bad.headers.get("access-control-allow-origin") is None


async def test_rate_limit_applies_to_expensive_endpoints(tmp_path, embedder, generator, scorer):
    settings = make_settings(tmp_path, rate_limit_per_minute=2)
    app = create_app(settings, build_container(settings, embedder, generator, scorer))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        codes = [
            (await c.post("/api/v1/retrieval/search", json={"query": "anything"})).status_code
            for _ in range(3)
        ]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429
