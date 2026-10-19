"""End-to-end integration check against a RUNNING backend.

Requires: backend running, Qdrant reachable, valid OPENAI_API_KEY on the server
(this script makes a few small paid API calls: embeddings + ~2 chat completions).

    python scripts/smoke_test.py --base-url http://localhost:8000/api/v1 [--api-key KEY]

Steps (each printed as PASS/FAIL, nothing is assumed):
 1. health  2. ready  3. upload sample corpus (wait)  4. chat with citations
 5. streaming chat  6. retrieval search  7. delete document  8. verify not retrievable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evaluations" / "sample_corpus" / "platform_guide.md"
QUESTION = "What are the default chunk size and chunk overlap?"


class Smoke:
    def __init__(self, base_url: str, api_key: str | None) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self.c = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=180)
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        self.failures += 0 if ok else 1
        return ok

    def run(self) -> int:
        r = self.c.get("/health")
        self.check("health", r.status_code == 200, json.dumps(r.json().get("components", {})))
        r = self.c.get("/ready")
        if not self.check("ready", r.status_code == 200, r.text[:300]):
            print("Backend not ready; aborting (check Qdrant and OPENAI_API_KEY).")
            return 1

        with CORPUS.open("rb") as fh:
            r = self.c.post(
                "/documents/upload",
                params={"wait": "true"},
                files=[("files", ("smoke_platform_guide.md", fh, "text/markdown"))],
            )
        res = r.json()["results"][0] if r.status_code == 202 else {}
        doc_id = res.get("document_id")
        if res.get("outcome") == "duplicate":
            print("  (corpus already indexed; reusing existing document)")
        self.check(
            "upload + ingestion", res.get("outcome") in {"indexed", "duplicate"}, str(res)[:300]
        )
        if not doc_id:
            return 1

        t = time.perf_counter()
        r = self.c.post("/chat", json={"question": QUESTION})
        body = r.json()
        retrieved = {c["chunk_id"] for c in (body.get("retrieval") or {}).get("chunks", [])}
        cites = body.get("citations", [])
        self.check(
            "chat answer with citations",
            r.status_code == 200 and bool(cites) and all(c["chunk_id"] in retrieved for c in cites),
            f"{(time.perf_counter() - t) * 1000:.0f} ms; answer: {body.get('answer', '')[:160]!r}",
        )

        events: list[str] = []
        tokens = 0
        with self.c.stream("POST", "/chat/stream", json={"question": QUESTION}) as s:
            for line in s.iter_lines():
                if line.startswith("event: "):
                    events.append(line[7:])
                    tokens += line == "event: token"
        self.check(
            "streaming (SSE)",
            events[:2] == ["start", "sources"] and events[-1] == "done" and "metadata" in events,
            f"{tokens} token events; sequence head={events[:3]} tail={events[-2:]}",
        )

        r = self.c.post("/retrieval/search", json={"query": "reciprocal rank fusion k"})
        ok = r.status_code == 200 and any(c["document_id"] == doc_id for c in r.json()["reranked"])
        self.check("retrieval search", ok, f"rerank_mode={r.json().get('rerank_mode')}")

        if res.get("outcome") == "duplicate":
            # Never delete a document this script did not create.
            print("  (skipping delete checks: the document existed before this run)")
            print(f"\n{self.failures} failure(s)")
            return 1 if self.failures else 0

        r = self.c.delete(f"/documents/{doc_id}")
        self.check("delete document", r.status_code == 200)
        r = self.c.post("/retrieval/search", json={"query": "reciprocal rank fusion k"})
        gone = all(c["document_id"] != doc_id for c in r.json().get("reranked", []))
        self.check("deleted document not retrievable", r.status_code == 200 and gone)

        print(f"\n{self.failures} failure(s)")
        return 1 if self.failures else 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000/api/v1"))
    p.add_argument("--api-key", default=os.getenv("API_KEY") or None)
    args = p.parse_args()
    sys.exit(Smoke(args.base_url, args.api_key).run())


if __name__ == "__main__":
    main()
