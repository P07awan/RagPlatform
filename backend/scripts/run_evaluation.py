"""Start an evaluation through the API and wait for it to finish.

    python scripts/run_evaluation.py --dataset sample_dataset --limit 5

LLM-judged RAGAS metrics call the OpenAI API (roughly 10 calls per case with the default
metrics) – start with a small --limit to gauge cost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000/api/v1"))
    p.add_argument("--api-key", default=os.getenv("API_KEY") or None)
    p.add_argument("--dataset", default="sample_dataset")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=60) as c:
        pre = c.get("/evaluations/prerequisites").json()
        if not pre.get("ready"):
            print("Cannot run evaluation:")
            for m in pre.get("missing", []):
                print(f"  - {m}")
            sys.exit(1)
        body: dict[str, object] = {"dataset": args.dataset}
        if args.limit:
            body["limit"] = args.limit
        r = c.post("/evaluations/run", json=body)
        if r.status_code != 202:
            print(f"Failed to start: HTTP {r.status_code} {r.text}")
            sys.exit(1)
        run = r.json()
        eid = run["evaluation_id"]
        print(f"Started evaluation {eid} ({run['total_cases']} cases)")
        while run["status"] in {"queued", "running"}:
            time.sleep(5)
            run = c.get(f"/evaluations/{eid}").json()
            done = run["completed_cases"] + run["failed_cases"]
            print(f"  {run['status']}: {done}/{run['total_cases']}")
        print(
            json.dumps(
                {
                    k: run[k]
                    for k in ("status", "metrics", "failed_cases", "duration_seconds", "error")
                },
                indent=2,
            )
        )
        sys.exit(0 if run["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
