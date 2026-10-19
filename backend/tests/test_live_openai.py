"""Live tests against the real OpenAI API (opt-in, incurs small API cost).

Run with:  pytest -m openai     (requires OPENAI_API_KEY in the environment or .env)
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.core.config import Settings
from app.core.container import AppContainer
from app.main import create_app
from app.rag.reranker import CrossEncoderReranker
from app.storage.sqlite_store import SQLiteStore
from tests.conftest import OverlapScorer

pytestmark = pytest.mark.openai


@pytest.fixture
def live_settings(tmp_path):
    try:
        s = Settings(  # reads OPENAI_* from env/.env
            environment="test",
            qdrant_path=":memory:",
            qdrant_collection_name="live_test",
            data_dir=tmp_path,
            api_key=None,
            enable_cache=False,
            langsmith_tracing=False,
        )
    except Exception as exc:
        pytest.skip(f"settings invalid: {exc}")
    if not s.openai_configured:
        pytest.skip("OPENAI_API_KEY not set")
    return s


async def test_live_ingest_and_answer(live_settings, sample_corpus):
    container = AppContainer(
        live_settings,
        store=SQLiteStore(":memory:"),
        # Keep this test independent of the HF model download.
        reranker=CrossEncoderReranker("overlap", scorer=OverlapScorer()),
    )
    app = create_app(live_settings, container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=120) as c:
            r = await c.post(
                "/api/v1/documents/upload",
                params={"wait": "true"},
                files=[("files", ("guide.md", sample_corpus, "text/markdown"))],
            )
            assert r.json()["results"][0]["outcome"] == "indexed", r.text
            body = (
                await c.post("/api/v1/chat", json={"question": "What is the default chunk size?"})
            ).json()
    assert body["citations"], body
    assert "800" in body["answer"]
    assert os.environ.get("LANGSMITH_TRACING") == "false"
