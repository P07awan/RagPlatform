"""Upload validation: extension allow-list, content sniffing, size limits, safe names."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
}

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._\- ()]+")


class FileValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedFile:
    safe_name: str
    extension: str
    file_type: str


def sanitize_filename(filename: str | None) -> str:
    """Return a display-safe base name. Never used to build server filesystem paths."""
    if not filename:
        raise FileValidationError("Missing filename")
    # Strip any directory components (both separators) to defeat path traversal.
    name = PurePath(filename.replace("\\", "/")).name
    name = unicodedata.normalize("NFKC", name).strip().strip(".")
    name = _UNSAFE_CHARS.sub("_", name)[:200]
    if not name:
        raise FileValidationError("Invalid filename")
    return name


def validate_filename(filename: str | None) -> ValidatedFile:
    safe = sanitize_filename(filename)
    ext = PurePath(safe).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise FileValidationError(f"Unsupported file type '{ext or 'none'}'. Allowed: {allowed}")
    return ValidatedFile(safe_name=safe, extension=ext, file_type=ALLOWED_EXTENSIONS[ext])


def validate_content_header(head: bytes, file_type: str) -> None:
    """Check magic bytes / encoding of the first bytes of the upload."""
    if not head:
        raise FileValidationError("File is empty")
    if file_type == "pdf":
        if not head.lstrip()[:5] == b"%PDF-":
            raise FileValidationError("File does not look like a valid PDF")
        return
    # Text formats: reject binary content (NUL bytes) and non-UTF-8 data.
    if b"\x00" in head:
        raise FileValidationError("Text file appears to contain binary data")
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # The sniff window may cut a multi-byte sequence; only fail if the error is early.
        if exc.start < len(head) - 4:
            raise FileValidationError("Text file must be UTF-8 encoded") from exc
