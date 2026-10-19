"""OpenAI embeddings with batching and bounded concurrency."""

from __future__ import annotations

import asyncio
from typing import Protocol

import openai
from openai import AsyncOpenAI

from app.core.config import Settings
from app.rag.openai_client import raise_openai_error


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    """Embeds text with the configured model. The same instance is used for ingestion and
    queries so vectors always come from one model/dimension."""

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        dimensions: int,
        send_dimensions: bool,
        batch_size: int = 64,
        concurrency: int = 2,
    ) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions
        self._send_dimensions = send_dimensions
        self.batch_size = batch_size
        self._semaphore = asyncio.Semaphore(concurrency)

    @classmethod
    def from_settings(cls, client: AsyncOpenAI, settings: Settings) -> OpenAIEmbedder:
        return cls(
            client,
            model=settings.openai_embedding_model,
            dimensions=settings.vector_size,
            # Only text-embedding-3-* accept the `dimensions` parameter.
            send_dimensions=settings.embedding_dimensions is not None,
            batch_size=settings.embedding_batch_size,
            concurrency=settings.ingestion_concurrency,
        )

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        kwargs: dict[str, object] = {"model": self.model, "input": batch}
        if self._send_dimensions:
            kwargs["dimensions"] = self.dimensions
        async with self._semaphore:
            try:
                response = await self.client.embeddings.create(**kwargs)  # type: ignore[arg-type]
            except openai.OpenAIError as exc:
                raise_openai_error(exc, "embedding")
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        if len(vectors) != len(batch):
            raise ValueError("Embedding API returned an unexpected number of vectors")
        for vec in vectors:
            if len(vec) != self.dimensions:
                raise ValueError(
                    f"Embedding dimension {len(vec)} does not match configured {self.dimensions}"
                )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        batches = [texts[i : i + self.batch_size] for i in range(0, len(texts), self.batch_size)]
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        return [vec for batch in results for vec in batch]

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed_batch([text]))[0]
