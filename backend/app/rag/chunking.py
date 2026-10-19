"""Configurable, structure-aware chunking built on LangChain's recursive splitter."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.loaders import LoadedDocument

# Stable namespace so chunk IDs are deterministic for (document_id, chunk_index).
CHUNK_NAMESPACE = uuid.UUID("8f2b3a52-6a41-4c1f-9a76-1f0e3c5b2d10")

MARKDOWN_SEPARATORS = ["\n# ", "\n## ", "\n### ", "\n#### ", "\n\n", "\n", ". ", " ", ""]
TEXT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    chunk_index: int
    text: str
    page_number: int | None


def make_chunk_id(document_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(CHUNK_NAMESPACE, f"{document_id}:{chunk_index}"))


def chunk_document(
    document: LoadedDocument,
    *,
    document_id: str,
    file_type: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Split each page separately so every chunk keeps an accurate page number."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=MARKDOWN_SEPARATORS if file_type == "markdown" else TEXT_SEPARATORS,
        keep_separator="start",
        strip_whitespace=True,
    )
    chunks: list[Chunk] = []
    for page in document.pages:
        for piece in splitter.split_text(page.text):
            piece = piece.strip()
            if not piece:
                continue
            idx = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(document_id, idx),
                    chunk_index=idx,
                    text=piece,
                    page_number=page.page_number,
                )
            )
    return chunks
