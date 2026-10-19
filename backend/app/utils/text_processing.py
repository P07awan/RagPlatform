"""Text cleaning, normalization and tokenization helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_SPACE = re.compile("[ \t\u00a0]+")  # spaces, tabs, non-breaking spaces
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_TOKEN = re.compile(r"[a-z0-9]+(?:['.][a-z0-9]+)*")

# Small English stopword list – keeps BM25 focused on content words.
STOPWORDS = frozenset(
    (
        "a an and are as at be but by for from has have how i if in into is it its of on or "
        "s such t that the their then there these they this to was were what when where which "
        "who why will with you your do does did can"
    ).split()
)


def clean_text(text: str) -> str:
    """Normalize extracted text while keeping paragraph and list structure."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)  # re-join words hyphenated across lines
    lines = [_MULTI_SPACE.sub(" ", line).rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def normalize_query(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def tokenize(text: str) -> list[str]:
    """Deterministic tokenizer shared by BM25 indexing and querying."""
    tokens = _TOKEN.findall(unicodedata.normalize("NFKC", text).lower())
    return [t for t in tokens if t not in STOPWORDS]


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def excerpt(text: str, max_chars: int = 300) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + "…"
