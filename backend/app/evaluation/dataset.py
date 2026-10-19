"""Evaluation datasets: JSONL files in ``EVALUATIONS_DIR`` (one case per line).

Case schema::

    {"id": "fmt-01", "question": "...", "reference_answer": "...",
     "reference_contexts": ["..."], "metadata": {"topic": "...", "expect_insufficient": false}}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.exceptions import NotFoundError, ValidationFailed

_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class EvalCase(BaseModel):
    id: str | None = None
    question: str = Field(min_length=1, max_length=4000)
    reference_answer: str | None = None
    reference_contexts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def expect_insufficient(self) -> bool:
        return bool(self.metadata.get("expect_insufficient"))


def dataset_path(directory: Path, name: str) -> Path:
    # Names are validated against a strict pattern so they can never escape the directory.
    if not _NAME.match(name):
        raise ValidationFailed("Invalid dataset name")
    path = directory / f"{name}.jsonl"
    if not path.is_file():
        raise NotFoundError(f"Dataset '{name}' not found")
    return path


def load_dataset(directory: Path, name: str, limit: int | None = None) -> list[EvalCase]:
    path = dataset_path(directory, name)
    cases: list[EvalCase] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(EvalCase.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValidationFailed(
                    f"Dataset '{name}' line {line_no} is invalid: {exc}"
                ) from exc
            if limit and len(cases) >= limit:
                break
    if not cases:
        raise ValidationFailed(f"Dataset '{name}' is empty")
    return cases


def list_datasets(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.jsonl")):
        if not _NAME.match(path.stem):
            continue
        with path.open(encoding="utf-8") as fh:
            count = sum(1 for line in fh if line.strip())
        out.append({"name": path.stem, "cases": count, "description": None})
    return out
