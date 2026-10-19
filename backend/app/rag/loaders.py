"""Text extraction for PDF, TXT and Markdown files.

Files are read from a temporary path on disk (uploads are streamed to disk, not held in
memory). PDFs are processed page by page so page numbers can be preserved.
OCR is *not* configured: PDFs without an extractable text layer are rejected with an
explicit message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.utils.text_processing import clean_text

logger = logging.getLogger(__name__)

# A page with fewer non-whitespace characters than this is treated as "no text layer".
MIN_CHARS_PER_DOCUMENT = 20


class DocumentLoadError(ValueError):
    """The document could not be read or contains no usable text."""


@dataclass(frozen=True)
class LoadedPage:
    text: str
    page_number: int | None  # 1-based; None when the format has no pages


@dataclass(frozen=True)
class LoadedDocument:
    pages: list[LoadedPage]
    page_count: int | None

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)


def _load_pdf(path: Path) -> LoadedDocument:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # Many PDFs are "encrypted" with an empty user password; anything else is rejected.
            try:
                if not reader.decrypt(""):
                    raise DocumentLoadError("PDF is password-protected")
            except DocumentLoadError:
                raise
            except Exception as exc:
                raise DocumentLoadError("PDF is encrypted and cannot be read") from exc
        pages: list[LoadedPage] = []
        total = len(reader.pages)
        for idx, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception as exc:  # pypdf can raise many internal errors on bad pages
                logger.warning("failed to extract PDF page", extra={"page": idx, "error": str(exc)})
                raw = ""
            text = clean_text(raw)
            if text:
                pages.append(LoadedPage(text=text, page_number=idx))
    except DocumentLoadError:
        raise
    except (PdfReadError, ValueError, OSError) as exc:
        raise DocumentLoadError(f"Unreadable PDF: {exc}") from exc

    if total == 0:
        raise DocumentLoadError("PDF has no pages")
    if sum(len(p.text.strip()) for p in pages) < MIN_CHARS_PER_DOCUMENT:
        raise DocumentLoadError(
            "No extractable text found. The PDF is probably scanned/image-only; "
            "OCR is not configured on this server."
        )
    return LoadedDocument(pages=pages, page_count=total)


def _load_text(path: Path) -> LoadedDocument:
    try:
        raw = path.read_text(encoding="utf-8-sig")  # tolerate a UTF-8 BOM
    except UnicodeDecodeError as exc:
        raise DocumentLoadError("Text file must be UTF-8 encoded") from exc
    text = clean_text(raw)
    if len(text) < MIN_CHARS_PER_DOCUMENT:
        raise DocumentLoadError("Document is empty or contains too little text")
    return LoadedDocument(pages=[LoadedPage(text=text, page_number=None)], page_count=None)


def load_document(path: Path, file_type: str) -> LoadedDocument:
    if file_type == "pdf":
        return _load_pdf(path)
    if file_type in {"text", "markdown"}:
        return _load_text(path)
    raise DocumentLoadError(f"Unsupported file type: {file_type}")
