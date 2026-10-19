"""In-memory BM25 lexical index with incremental add/remove.

Scoring is Okapi BM25 with the Lucene IDF variant ``log(1 + (N - df + 0.5) / (df + 0.5))``
which is always positive (classic Okapi IDF goes negative for terms in > 50% of docs,
which breaks tiny corpora).

Source of truth: chunk payloads in Qdrant. On startup the index is rebuilt by scrolling
the collection; afterwards ingestion/deletion keep it in sync incrementally.

Limitations: the whole lexical corpus (tokens + chunk text) lives in process memory and
is per-process (each worker holds its own copy). To scale, swap this class for a
persistent lexical index – Qdrant sparse vectors (BM25/SPLADE), OpenSearch/Elasticsearch
or Postgres full-text – behind the same ``search`` interface.
"""

from __future__ import annotations

import math
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.utils.text_processing import tokenize


@dataclass(frozen=True)
class LexicalHit:
    chunk_id: str
    score: float
    payload: dict[str, Any]


@dataclass
class _Entry:
    tf: Counter[str]
    length: int
    payload: dict[str, Any]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._entries: dict[str, _Entry] = {}
        self._postings: dict[str, set[str]] = {}
        self._by_document: dict[str, set[str]] = {}
        self._total_length = 0
        self._lock = threading.RLock()
        self.loaded = False  # True once rebuilt from the vector store

    # Mutation ---------------------------------------------------------------------------
    def add(self, chunk_id: str, text: str, payload: dict[str, Any]) -> None:
        tokens = tokenize(text)
        with self._lock:
            if chunk_id in self._entries:
                self._remove_chunk(chunk_id)
            tf = Counter(tokens)
            self._entries[chunk_id] = _Entry(tf=tf, length=len(tokens), payload=payload)
            self._total_length += len(tokens)
            for term in tf:
                self._postings.setdefault(term, set()).add(chunk_id)
            self._by_document.setdefault(payload["document_id"], set()).add(chunk_id)

    def add_many(self, items: list[tuple[str, str, dict[str, Any]]]) -> None:
        with self._lock:
            for chunk_id, text, payload in items:
                self.add(chunk_id, text, payload)

    def _remove_chunk(self, chunk_id: str) -> None:
        entry = self._entries.pop(chunk_id, None)
        if entry is None:
            return
        self._total_length -= entry.length
        for term in entry.tf:
            ids = self._postings.get(term)
            if ids is not None:
                ids.discard(chunk_id)
                if not ids:
                    del self._postings[term]
        doc_ids = self._by_document.get(entry.payload["document_id"])
        if doc_ids is not None:
            doc_ids.discard(chunk_id)
            if not doc_ids:
                del self._by_document[entry.payload["document_id"]]

    def remove_document(self, document_id: str) -> int:
        with self._lock:
            chunk_ids = list(self._by_document.get(document_id, ()))
            for chunk_id in chunk_ids:
                self._remove_chunk(chunk_id)
            return len(chunk_ids)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._postings.clear()
            self._by_document.clear()
            self._total_length = 0

    # Query ------------------------------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self._entries)

    def document_ids(self) -> set[str]:
        with self._lock:
            return set(self._by_document)

    def search(
        self, query: str, limit: int, document_ids: list[str] | None = None
    ) -> list[LexicalHit]:
        terms = tokenize(query)
        if not terms or limit <= 0:
            return []
        with self._lock:
            n_docs = len(self._entries)
            if n_docs == 0:
                return []
            avgdl = self._total_length / n_docs if n_docs else 0.0
            allowed = set(document_ids) if document_ids else None
            query_tf = Counter(terms)
            scores: dict[str, float] = {}
            for term, qf in query_tf.items():
                postings = self._postings.get(term)
                if not postings:
                    continue
                df = len(postings)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                for chunk_id in postings:
                    entry = self._entries[chunk_id]
                    if allowed is not None and entry.payload["document_id"] not in allowed:
                        continue
                    freq = entry.tf[term]
                    norm = 1 - self.b + self.b * (entry.length / avgdl if avgdl else 0)
                    term_score = idf * (freq * (self.k1 + 1)) / (freq + self.k1 * norm)
                    scores[chunk_id] = scores.get(chunk_id, 0.0) + term_score * qf
            ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
            return [
                LexicalHit(chunk_id=cid, score=score, payload=self._entries[cid].payload)
                for cid, score in ranked
            ]
