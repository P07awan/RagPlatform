"""SQLite persistence for document registry, evaluation runs and chat activity.

Why SQLite: zero-ops, durable on local disk / a mounted volume, and enough for a
single-instance deployment. Vectors and chunk text live in Qdrant; this store keeps
metadata and job status. For multi-instance deployments move this to Postgres
(the SQL is portable).

All public methods are synchronous and cheap; async callers wrap them with
``asyncio.to_thread`` via :class:`AsyncStore`.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    page_count INTEGER,
    embedding_model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    evaluation_id TEXT PRIMARY KEY,
    dataset TEXT NOT NULL,
    status TEXT NOT NULL,
    total_cases INTEGER NOT NULL,
    completed_cases INTEGER NOT NULL DEFAULT 0,
    failed_cases INTEGER NOT NULL DEFAULT 0,
    metrics TEXT,
    config TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_seconds REAL
);

CREATE TABLE IF NOT EXISTS evaluation_results (
    evaluation_id TEXT NOT NULL,
    case_index INTEGER NOT NULL,
    case_id TEXT,
    question TEXT NOT NULL,
    reference_answer TEXT,
    generated_answer TEXT,
    retrieved_contexts TEXT,
    reference_contexts TEXT,
    scores TEXT,
    error TEXT,
    latency_ms REAL,
    PRIMARY KEY (evaluation_id, case_index),
    FOREIGN KEY (evaluation_id) REFERENCES evaluation_runs(evaluation_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id TEXT,
    question_preview TEXT,
    latency_ms REAL,
    citation_count INTEGER,
    cache_hit INTEGER,
    insufficient_context INTEGER,
    status TEXT
);
"""

CHAT_ACTIVITY_RETENTION = 500


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _json_load(value: str | None) -> Any:
    return json.loads(value) if value else None


class SQLiteStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # PRAGMAs must run outside a transaction to take effect.
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN")
                yield cur
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # Documents -------------------------------------------------------------------------
    def create_document(self, record: dict[str, Any]) -> None:
        now = utcnow()
        row = {
            "created_at": now,
            "updated_at": now,
            "error": None,
            "chunk_count": 0,
            "page_count": None,
            "embedding_model": None,
            "indexed_at": None,
            **record,
        }
        cols = ", ".join(row)
        params = ", ".join(f":{c}" for c in row)
        with self._tx() as cur:
            cur.execute(f"INSERT INTO documents ({cols}) VALUES ({params})", row)

    def update_document(self, document_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        with self._tx() as cur:
            cur.execute(
                f"UPDATE documents SET {assignments} WHERE document_id = :document_id",
                {**fields, "document_id": document_id},
            )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        return dict(row) if row else None

    def find_document_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE content_hash = ? ORDER BY created_at DESC LIMIT 1",
                (content_hash,),
            ).fetchone()
        return dict(row) if row else None

    def list_documents(
        self, *, limit: int, offset: int, status: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = ("WHERE status = ?", [status]) if status else ("", [])
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM documents {where}", params
            ).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT * FROM documents {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def document_status_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def delete_document(self, document_id: str) -> None:
        with self._tx() as cur:
            cur.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))

    def mark_interrupted_documents(self) -> int:
        """Documents left pending/processing by a previous process cannot resume."""
        with self._tx() as cur:
            cur.execute(
                "UPDATE documents SET status = 'failed', error = ?, updated_at = ? "
                "WHERE status IN ('pending', 'processing')",
                ("Ingestion interrupted by a server restart; please upload again.", utcnow()),
            )
            return cur.rowcount

    # Evaluations -----------------------------------------------------------------------
    def create_evaluation(self, record: dict[str, Any]) -> None:
        row = {"created_at": utcnow(), **record}
        row["config"] = json.dumps(row.get("config") or {})
        cols = ", ".join(row)
        params = ", ".join(f":{c}" for c in row)
        with self._tx() as cur:
            cur.execute(f"INSERT INTO evaluation_runs ({cols}) VALUES ({params})", row)

    def update_evaluation(self, evaluation_id: str, **fields: Any) -> None:
        if "metrics" in fields:
            fields["metrics"] = json.dumps(fields["metrics"])
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        with self._tx() as cur:
            cur.execute(
                f"UPDATE evaluation_runs SET {assignments} WHERE evaluation_id = :evaluation_id",
                {**fields, "evaluation_id": evaluation_id},
            )

    @staticmethod
    def _eval_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metrics"] = _json_load(data.get("metrics")) or {}
        data["config"] = _json_load(data.get("config")) or {}
        return data

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM evaluation_runs WHERE evaluation_id = ?", (evaluation_id,)
            ).fetchone()
        return self._eval_row(row) if row else None

    def list_evaluations(self, *, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0]
            rows = self._conn.execute(
                "SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._eval_row(r) for r in rows], total

    def has_active_evaluation(self) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM evaluation_runs WHERE status IN ('queued', 'running') LIMIT 1"
            ).fetchone()
        return row is not None

    def save_evaluation_result(self, evaluation_id: str, result: dict[str, Any]) -> None:
        row = {
            "evaluation_id": evaluation_id,
            "case_index": result["case_index"],
            "case_id": result.get("case_id"),
            "question": result["question"],
            "reference_answer": result.get("reference_answer"),
            "generated_answer": result.get("generated_answer"),
            "retrieved_contexts": json.dumps(result.get("retrieved_contexts") or []),
            "reference_contexts": json.dumps(result.get("reference_contexts") or []),
            "scores": json.dumps(result.get("scores") or {}),
            "error": result.get("error"),
            "latency_ms": result.get("latency_ms"),
        }
        cols = ", ".join(row)
        params = ", ".join(f":{c}" for c in row)
        with self._tx() as cur:
            cur.execute(
                f"INSERT OR REPLACE INTO evaluation_results ({cols}) VALUES ({params})", row
            )

    def list_evaluation_results(self, evaluation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM evaluation_results WHERE evaluation_id = ? ORDER BY case_index",
                (evaluation_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["retrieved_contexts"] = _json_load(d["retrieved_contexts"]) or []
            d["reference_contexts"] = _json_load(d["reference_contexts"]) or []
            d["scores"] = _json_load(d["scores"]) or {}
            out.append(d)
        return out

    def mark_interrupted_evaluations(self) -> int:
        with self._tx() as cur:
            cur.execute(
                "UPDATE evaluation_runs SET status = 'interrupted', error = ?, finished_at = ? "
                "WHERE status IN ('queued', 'running')",
                ("Evaluation interrupted by a server restart.", utcnow()),
            )
            return cur.rowcount

    # Chat activity ---------------------------------------------------------------------
    def record_chat(self, record: dict[str, Any]) -> None:
        row = {"created_at": utcnow(), **record}
        cols = ", ".join(row)
        params = ", ".join(f":{c}" for c in row)
        with self._tx() as cur:
            cur.execute(f"INSERT INTO chat_activity ({cols}) VALUES ({params})", row)
            cur.execute(
                "DELETE FROM chat_activity WHERE id NOT IN "
                "(SELECT id FROM chat_activity ORDER BY id DESC LIMIT ?)",
                (CHAT_ACTIVITY_RETENTION,),
            )

    def recent_chats(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM chat_activity ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["cache_hit"] = bool(d["cache_hit"])
            d["insufficient_context"] = bool(d["insufficient_context"])
            out.append(d)
        return out


class AsyncStore:
    """Thin async facade running SQLite calls in a worker thread."""

    def __init__(self, store: SQLiteStore) -> None:
        self.sync = store

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.sync, name)
        if not callable(attr):
            return attr

        async def _call(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(attr, *args, **kwargs)

        return _call
