"""Shared fixtures. Paid APIs are replaced by deterministic fakes; Qdrant runs in-memory.

The fakes are test doubles only – they are never used by the application at runtime.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.container import AppContainer
from app.evaluation.dataset import EvalCase
from app.main import create_app
from app.rag.reranker import CrossEncoderReranker
from app.rag.vector_store import VectorStore, build_qdrant_client
from app.storage.sqlite_store import SQLiteStore
from app.utils.text_processing import tokenize

DIM = 64
BACKEND_DIR = Path(__file__).resolve().parents[1]


class FakeEmbedder:
    """Hashed bag-of-words embedding: texts sharing words get similar vectors."""

    model = "fake-embedding"

    def __init__(self, dimensions: int = DIM) -> None:
        self.dimensions = dimensions
        self.calls = 0

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dimensions
        for tok in tokenize(text) or ["empty"]:
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dimensions] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return self._vec(text)


class FakeGenerator:
    """Streams a canned answer citing passage [1] (or a configured answer)."""

    model = "fake-llm"

    def __init__(self, answer: str | None = None, fail: Exception | None = None) -> None:
        self.answer = answer
        self.fail = fail
        self.calls = 0
        self.last_messages: list[dict[str, str]] | None = None

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        self.calls += 1
        self.last_messages = messages
        if self.fail:
            raise self.fail
        answer = self.answer or "Based on the documents, the answer is stated in the context [1]."
        for piece in re.findall(r"\S+\s*", answer):
            yield piece


class OverlapScorer:
    """Cross-encoder stand-in: scores by query/passage token overlap."""

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.calls += 1
        out = []
        for q, p in pairs:
            qt, pt = set(tokenize(q)), set(tokenize(p))
            out.append(len(qt & pt) / (len(qt) or 1))
        return out


class FakeScorer:
    metric_names = ("faithfulness", "answer_relevancy")

    async def score(
        self, case: EvalCase, answer: str, contexts: list[str], insufficient: bool
    ) -> tuple[dict[str, float | None], list[str]]:
        if case.expect_insufficient:
            return {"abstention": 1.0 if insufficient else 0.0}, []
        return {"faithfulness": 1.0 if contexts else 0.0, "answer_relevancy": 0.5}, []


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "openai_api_key": None,
        "api_key": None,
        "qdrant_path": ":memory:",
        "qdrant_collection_name": "test_docs",
        "openai_embedding_model": "fake-embedding",
        "embedding_dimensions": DIM,
        "data_dir": tmp_path / "data",
        "evaluations_dir": BACKEND_DIR / "evaluations",
        "chunk_size": 300,
        "chunk_overlap": 50,
        "retrieval_top_k": 8,
        "rerank_top_k": 3,
        "rate_limit_per_minute": 0,
        "log_json": False,
        "langsmith_tracing": False,
        "enable_cache": False,
        "redis_url": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def generator() -> FakeGenerator:
    return FakeGenerator()


@pytest.fixture
def scorer() -> OverlapScorer:
    return OverlapScorer()


def build_container(
    settings: Settings,
    embedder: FakeEmbedder,
    generator: FakeGenerator,
    scorer: OverlapScorer,
    **kwargs: Any,
) -> AppContainer:
    return AppContainer(
        settings,
        embedder=embedder,
        generator=generator,
        reranker=kwargs.pop("reranker", CrossEncoderReranker("fake-cross-encoder", scorer=scorer)),
        vector_store=VectorStore(
            build_qdrant_client(settings), settings.qdrant_collection_name, settings.vector_size
        ),
        store=SQLiteStore(":memory:"),
        evaluation_backend=kwargs.pop("evaluation_backend", FakeScorer()),
        **kwargs,
    )


@pytest.fixture
def container(
    settings: Settings, embedder: FakeEmbedder, generator: FakeGenerator, scorer: OverlapScorer
) -> AppContainer:
    return build_container(settings, embedder, generator, scorer)


@pytest.fixture
def app(settings: Settings, container: AppContainer) -> FastAPI:
    return create_app(settings, container)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
def sample_corpus() -> bytes:
    return (BACKEND_DIR / "evaluations" / "sample_corpus" / "platform_guide.md").read_bytes()


@pytest.fixture
def anyio_backend() -> Iterator[str]:
    yield "asyncio"


def minimal_pdf(pages: list[str]) -> bytes:
    """Build a small valid PDF with one Helvetica text line per page."""
    objects: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, text in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
