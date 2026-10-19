# RAG Platform – Backend

FastAPI service exposing `/api/v1`: ingestion, hybrid retrieval, reranking, grounded chat (JSON and
SSE) and RAGAS evaluation. See the root README for architecture, deployment and security.

## Quick start (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env        # set OPENAI_API_KEY
docker compose -f ..\docker-compose.yml up -d qdrant   # or set QDRANT_PATH=./data/qdrant (dev only)
uvicorn app.main:app --reload --port 8000
```
Swagger: <http://localhost:8000/docs>.

## Layout

```
app/
  main.py               app factory, lifespan, middleware, CORS
  api/router.py         public health + key-protected routers
  api/routes/           health, documents, ingestion, chat, retrieval, evaluation, system
  core/                 config (pydantic-settings), container (wiring), logging, security,
                        exceptions, tracing
  services/             document_service, chat_service (SSE), evaluation_service, cache
  rag/                  loaders, chunking, embeddings, vector_store, bm25_retriever,
                        hybrid_retriever, reranker, prompts, generator, graph (LangGraph), pipeline
  evaluation/           dataset, metrics (RAGAS), runner
  storage/sqlite_store  documents, evaluation runs/results, chat activity
  middleware/           request_id, timing (pure ASGI – streaming safe)
  utils/                file_validation, text_processing
evaluations/            sample_dataset.jsonl (35 cases) + sample_corpus/platform_guide.md
scripts/                smoke_test.py, ingest_sample_corpus.py, run_evaluation.py, reindex.py
tests/                  pytest suite (fakes for OpenAI, in-memory Qdrant)
```

Route handlers only validate input and call services; all logic lives in `services/` and `rag/`.
`AppContainer` builds every component once; tests inject fakes through its constructor.

## Design decisions

* **LangGraph** nodes are small closures over injected dependencies; streaming uses LangGraph's
  custom stream writer, so the same graph serves `/chat` (`ainvoke`) and `/chat/stream` (`astream`).
* **Own BM25 implementation** (Okapi with Lucene IDF) instead of `rank_bm25`, because it supports
  incremental add/remove and stays positive on tiny corpora.
* **Reranker** runs in a worker thread (`asyncio.to_thread`) so CPU inference never blocks the event loop.
* **No silent fallbacks**: no model switching on failure; reranker fallback only if configured, and labelled.
* **SQLite** for metadata (zero-ops, durable on a volume). Swap for Postgres to scale out.

## Resource notes

* Cross-encoder `ms-marco-MiniLM-L-6-v2`: ~90 MB download (Hugging Face cache), ~200–400 MB RSS.
  Loaded once on first rerank (`RERANKER_PRELOAD=true` loads at startup).
* PyTorch CPU wheels are ~200 MB installed.
* Uploads are capped (`MAX_UPLOAD_SIZE_MB`) and streamed to disk; extracted text of one document is
  held in memory while chunking.

## Tests

```powershell
pytest              # 150 tests, offline, no API cost
pytest -m slow      # real cross-encoder
pytest -m openai    # live OpenAI (needs key)
ruff check . ; ruff format --check .
```

## Scripts

| Script | Purpose |
|---|---|
| `scripts/smoke_test.py` | E2E check against a running backend (upload → chat → stream → delete → verify) |
| `scripts/ingest_sample_corpus.py` | Index the evaluation corpus |
| `scripts/run_evaluation.py` | Start an evaluation and poll to completion |
| `scripts/reindex.py` | Re-embed all chunks into a new collection after an embedding-model change |

## Production start command

`uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers` with **one worker** per instance
(in-memory BM25 + in-process jobs). Health check: `/api/v1/health`; readiness: `/api/v1/ready`.
