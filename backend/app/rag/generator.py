"""LLM answer generation (OpenAI Chat Completions, streamed)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

import openai
from openai import AsyncOpenAI

from app.rag.openai_client import raise_openai_error


class AnswerGenerator(Protocol):
    model: str

    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


class OpenAIGenerator:
    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        temperature: float | None,
        max_tokens: int,
    ) -> None:
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_completion_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        try:
            response = await self.client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            try:
                async for event in response:
                    if not event.choices:
                        continue
                    delta = event.choices[0].delta.content
                    if delta:
                        yield delta
            finally:
                await response.close()
        except openai.OpenAIError as exc:
            raise_openai_error(exc, "answer generation")
