"""Re-embed all stored chunks into a NEW collection (embedding model / dimension migration).

Chunk text is stored in each Qdrant payload, so original files are not needed.

    # 1. Set the new model in .env (e.g. OPENAI_EMBEDDING_MODEL=text-embedding-3-large)
    # 2. Run (backend can stay up, pointing at the old collection):
    python scripts/reindex.py --source rag_documents --target rag_documents_v2
    # 3. Set QDRANT_COLLECTION_NAME=rag_documents_v2 and restart the backend.
    # 4. After verifying, delete the old collection in Qdrant.

The source collection is never modified. Costs: one embedding call per 64 chunks.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.rag.embeddings import OpenAIEmbedder
from app.rag.openai_client import build_openai_client
from app.rag.vector_store import VectorPoint, VectorStore, build_qdrant_client


async def reindex(source: str, target: str, batch: int) -> None:
    settings = get_settings()
    client = build_qdrant_client(settings)
    if not await client.collection_exists(source):
        raise SystemExit(f"Source collection '{source}' does not exist")
    if await client.collection_exists(target):
        raise SystemExit(f"Target collection '{target}' already exists; choose a new name")
    embedder = OpenAIEmbedder.from_settings(build_openai_client(settings), settings)
    src = VectorStore(client, source, settings.vector_size)  # only used for scrolling
    dst = VectorStore(client, target, settings.vector_size)
    await dst.initialize()

    pending: list[tuple[str, dict]] = []
    total = 0

    async def flush() -> None:
        nonlocal total
        vectors = await embedder.embed_documents([p["content"] for _, p in pending])
        points = [
            VectorPoint(id=pid, vector=v, payload={**p, "embedding_model": embedder.model})
            for (pid, p), v in zip(pending, vectors, strict=True)
        ]
        total += await dst.upsert(points)
        pending.clear()
        print(f"  re-embedded {total} chunks")

    async for pid, payload in src.scroll_payloads():
        pending.append((pid, payload))
        if len(pending) >= batch:
            await flush()
    if pending:
        await flush()
    print(
        f"Done: {total} chunks in '{target}' "
        f"({settings.openai_embedding_model}, {settings.vector_size}d)."
    )
    print(f"Next: set QDRANT_COLLECTION_NAME={target} and restart the backend.")
    await client.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--batch", type=int, default=64)
    args = p.parse_args()
    asyncio.run(reindex(args.source, args.target, args.batch))


if __name__ == "__main__":
    main()
