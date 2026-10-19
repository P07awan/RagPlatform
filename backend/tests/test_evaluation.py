"""Evaluation datasets, runner, persistence and API (scoring backend mocked)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.core.exceptions import NotFoundError, ValidationFailed
from app.evaluation.dataset import list_datasets, load_dataset
from app.evaluation.metrics import SUPPORTED_METRICS, ragas_import_error, ragas_version
from app.evaluation.runner import aggregate, case_failed
from app.main import create_app
from tests.conftest import BACKEND_DIR, build_container, make_settings

SAMPLE_DIR = BACKEND_DIR / "evaluations"


def test_sample_dataset_is_valid_and_large_enough():
    cases = load_dataset(SAMPLE_DIR, "sample_dataset")
    assert len(cases) >= 30
    assert all(c.question and c.reference_answer for c in cases)
    assert len({c.id for c in cases}) == len(cases)
    assert any(c.expect_insufficient for c in cases)


def test_sample_reference_contexts_exist_in_corpus():
    corpus = (SAMPLE_DIR / "sample_corpus" / "platform_guide.md").read_text(encoding="utf-8")
    flat = " ".join(corpus.split())
    for case in load_dataset(SAMPLE_DIR, "sample_dataset"):
        for ctx in case.reference_contexts:
            assert " ".join(ctx.split()) in flat, f"{case.id}: reference context not in corpus"


def test_dataset_limit_and_listing():
    assert len(load_dataset(SAMPLE_DIR, "sample_dataset", limit=3)) == 3
    names = [d["name"] for d in list_datasets(SAMPLE_DIR)]
    assert "sample_dataset" in names


def test_dataset_validation_errors(tmp_path: Path):
    (tmp_path / "bad.jsonl").write_text('{"question": "ok"}\n{not json}\n', encoding="utf-8")
    with pytest.raises(ValidationFailed, match="line 2"):
        load_dataset(tmp_path, "bad")
    (tmp_path / "empty.jsonl").write_text("\n", encoding="utf-8")
    with pytest.raises(ValidationFailed, match="empty"):
        load_dataset(tmp_path, "empty")
    with pytest.raises(NotFoundError):
        load_dataset(tmp_path, "missing")
    with pytest.raises(ValidationFailed):
        load_dataset(tmp_path, "../etc/passwd")


def test_aggregate_ignores_missing_scores():
    results = [
        {"scores": {"faithfulness": 1.0, "answer_relevancy": None}},
        {"scores": {"faithfulness": 0.5, "answer_relevancy": 0.8}},
        {"scores": {}},
    ]
    assert aggregate(results) == {"answer_relevancy": 0.8, "faithfulness": 0.75}


def test_case_failed_rules():
    assert case_failed({"generated_answer": None, "scores": {"a": 1.0}})
    assert case_failed({"generated_answer": "x", "scores": {}})
    assert case_failed({"generated_answer": "x", "scores": {"a": None}})
    assert not case_failed({"generated_answer": "x", "scores": {"a": None, "b": 0.3}})


def test_installed_ragas_supports_required_metrics():
    assert ragas_version() is not None
    assert ragas_import_error() is None

    assert set(SUPPORTED_METRICS) == {
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
    }


def test_ragas_scorer_builds_metrics_without_network(tmp_path):
    from app.evaluation.metrics import RagasScorer

    scorer = RagasScorer(
        make_settings(
            tmp_path,
            openai_api_key="sk-test-not-used",
            openai_embedding_model="text-embedding-3-small",
            embedding_dimensions=None,
        )
    )
    assert scorer.metric_names == SUPPORTED_METRICS
    with pytest.raises(ValueError):
        RagasScorer(make_settings(tmp_path, openai_api_key="sk-x"), ["bleu"])


async def test_prerequisites_report_missing_documents(client):
    body = (await client.get("/api/v1/evaluations/prerequisites")).json()
    assert body["ready"] is False
    assert any("No documents are indexed" in m for m in body["missing"])


async def test_run_rejected_when_prerequisites_missing(client):
    r = await client.post("/api/v1/evaluations/run", json={"dataset": "sample_dataset", "limit": 2})
    assert r.status_code == 503
    assert r.json()["error"]["details"]


async def test_empty_evaluation_history(client):
    body = (await client.get("/api/v1/evaluations")).json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_evaluation_run_end_to_end(client, container, sample_corpus):
    await client.post(
        "/api/v1/documents/upload",
        params={"wait": "true"},
        files=[("files", ("platform_guide.md", sample_corpus, "text/markdown"))],
    )
    r = await client.post("/api/v1/evaluations/run", json={"dataset": "sample_dataset", "limit": 4})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] in {"queued", "running"} and run["total_cases"] == 4
    await container.evaluations.wait()

    done = (await client.get(f"/api/v1/evaluations/{run['evaluation_id']}")).json()
    assert done["status"] == "completed"
    assert done["completed_cases"] == 4 and done["failed_cases"] == 0
    assert set(done["metrics"]) == {"faithfulness", "answer_relevancy"}
    assert done["duration_seconds"] is not None
    assert done["config"]["metrics"] == ["faithfulness", "answer_relevancy"]

    results = (await client.get(f"/api/v1/evaluations/{run['evaluation_id']}/results")).json()[
        "items"
    ]
    assert len(results) == 4
    first = results[0]
    assert first["generated_answer"] and first["retrieved_contexts"]
    assert first["reference_answer"] and first["question"]

    listing = (await client.get("/api/v1/evaluations")).json()
    assert listing["total"] == 1
    stats = (await client.get("/api/v1/stats")).json()
    assert stats["last_evaluation"]["evaluation_id"] == run["evaluation_id"]


async def test_concurrent_runs_rejected(client, container, sample_corpus):
    await client.post(
        "/api/v1/documents/upload",
        params={"wait": "true"},
        files=[("files", ("g.md", sample_corpus, "text/markdown"))],
    )
    gate = asyncio.Event()
    original = container.pipeline.run

    async def slow_run(state):
        await gate.wait()
        return await original(state)

    container.pipeline.run = slow_run
    first = await client.post(
        "/api/v1/evaluations/run", json={"dataset": "sample_dataset", "limit": 1}
    )
    second = await client.post(
        "/api/v1/evaluations/run", json={"dataset": "sample_dataset", "limit": 1}
    )
    gate.set()
    await container.evaluations.wait()
    assert first.status_code == 202 and second.status_code == 409


async def test_unknown_dataset_and_evaluation(client, sample_corpus):
    await client.post(
        "/api/v1/documents/upload",
        params={"wait": "true"},
        files=[("files", ("g.md", sample_corpus, "text/markdown"))],
    )
    assert (
        await client.post("/api/v1/evaluations/run", json={"dataset": "nope"})
    ).status_code == 404
    assert (
        await client.post("/api/v1/evaluations/run", json={"dataset": "../x"})
    ).status_code == 422
    assert (await client.get("/api/v1/evaluations/unknown")).status_code == 404
    assert (await client.get("/api/v1/evaluations/unknown/results")).status_code == 404


async def test_failed_cases_recorded_with_errors(
    tmp_path, embedder, generator, scorer, sample_corpus
):
    from app.core.exceptions import UpstreamQuotaError

    settings = make_settings(tmp_path)
    container = build_container(settings, embedder, generator, scorer)
    app = create_app(settings, container)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        await c.post(
            "/api/v1/documents/upload",
            params={"wait": "true"},
            files=[("files", ("g.md", sample_corpus, "text/markdown"))],
        )
        generator.fail = UpstreamQuotaError(
            "OpenAI quota exhausted or billing not configured for this API key."
        )
        run = (
            await c.post("/api/v1/evaluations/run", json={"dataset": "sample_dataset", "limit": 2})
        ).json()
        await container.evaluations.wait()
        done = (await c.get(f"/api/v1/evaluations/{run['evaluation_id']}")).json()
        results = (await c.get(f"/api/v1/evaluations/{run['evaluation_id']}/results")).json()[
            "items"
        ]
    assert done["status"] == "failed" and done["failed_cases"] == 2
    assert done["metrics"] == {}  # never fabricated
    assert all("upstream_quota_exceeded" in r["error"] for r in results)


async def test_interrupted_runs_marked_on_startup(container):
    await container.store.create_evaluation(
        {"evaluation_id": "e1", "dataset": "d", "status": "running", "total_cases": 3, "config": {}}
    )
    await container.startup()
    run = await container.store.get_evaluation("e1")
    assert run["status"] == "interrupted"


def test_results_json_roundtrip(tmp_path):
    from app.storage.sqlite_store import SQLiteStore

    s = SQLiteStore(tmp_path / "x.db")
    s.create_evaluation(
        {
            "evaluation_id": "e",
            "dataset": "d",
            "status": "queued",
            "total_cases": 1,
            "config": {"a": 1},
        }
    )
    s.save_evaluation_result(
        "e",
        {
            "case_index": 0,
            "question": "q",
            "scores": {"faithfulness": 0.5},
            "retrieved_contexts": ["c"],
            "reference_contexts": [],
        },
    )
    s.update_evaluation("e", metrics={"faithfulness": 0.5}, status="completed")
    assert s.get_evaluation("e")["metrics"] == {"faithfulness": 0.5}
    assert s.list_evaluation_results("e")[0]["retrieved_contexts"] == ["c"]
    json.dumps(s.list_evaluation_results("e"))
    s.close()
