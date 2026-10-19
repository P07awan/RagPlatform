"""Upload the bundled sample corpus (needed before running the sample evaluation dataset).

    python scripts/ingest_sample_corpus.py --base-url http://localhost:8000/api/v1 [--api-key KEY]

Costs: one embedding batch for ~25 chunks (a fraction of a cent with text-embedding-3-small).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

CORPUS_DIR = Path(__file__).resolve().parents[1] / "evaluations" / "sample_corpus"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000/api/v1"))
    p.add_argument("--api-key", default=os.getenv("API_KEY") or None)
    args = p.parse_args()
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    files = sorted(CORPUS_DIR.glob("*.md"))
    with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=300) as c:
        handles = [f.open("rb") for f in files]
        try:
            r = c.post(
                "/documents/upload",
                params={"wait": "true"},
                files=[
                    ("files", (f.name, h, "text/markdown"))
                    for f, h in zip(files, handles, strict=True)
                ],
            )
        finally:
            for h in handles:
                h.close()
    if r.status_code != 202:
        print(f"Upload failed: HTTP {r.status_code} {r.text}")
        sys.exit(1)
    for res in r.json()["results"]:
        print(f"{res['filename']}: {res['outcome']} — {res.get('message')}")
    sys.exit(0 if all(x["outcome"] in {"indexed", "duplicate"} for x in r.json()["results"]) else 1)


if __name__ == "__main__":
    main()
