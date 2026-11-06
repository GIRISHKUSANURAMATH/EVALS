"""Dataset export to JSONL, CSV and JSON with schema validation.

Record layout is designed to drop into common eval tooling: ``input`` / ``expected_output``
/ ``actual_output`` columns plus an OpenAI-style ``messages`` array for chat evaluation.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.privacy.redactor import Redactor

ExportFormat = Literal["jsonl", "csv", "json"]


class ExportRecord(BaseModel):
    id: str
    input: str
    expected_output: str | None
    expected_output_source: Literal["none", "candidate", "human_approved"]
    actual_output: str | None
    category: str
    failure_type: str | None
    failure_evidence: Literal["observed", "heuristic", "none"]
    review_status: Literal["pending", "approved", "rejected", "flagged"]
    confidence_score: float = Field(ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    source_trace_id: str
    source_timestamp: str | None
    system_prompt: str | None
    messages: list[dict[str, Any]]
    metadata: dict[str, Any]


class ExportValidationError(ValueError):
    pass


def example_to_record(ex: Any) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    if ex.system_prompt:
        messages.append({"role": "system", "content": ex.system_prompt})
    messages.extend(ex.context or [])
    messages.append({"role": "user", "content": ex.input})
    return {
        "id": ex.id,
        "input": ex.input,
        "expected_output": ex.expected_output,
        "expected_output_source": ex.expected_output_source,
        "actual_output": ex.actual_output,
        "category": ex.category,
        "failure_type": ex.failure_type,
        "failure_evidence": ex.failure_evidence,
        "review_status": ex.review_status,
        "confidence_score": ex.confidence_score,
        "quality_score": ex.quality_score,
        "source_trace_id": ex.source_trace_key,
        "source_timestamp": ex.source_timestamp.isoformat()
        if isinstance(ex.source_timestamp, datetime)
        else ex.source_timestamp,
        "system_prompt": ex.system_prompt,
        "messages": messages,
        "metadata": ex.metadata_ if hasattr(ex, "metadata_") else ex.metadata,
    }


def validate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate every record against the export schema and run a final secret scan."""
    redactor = Redactor()
    validated: list[dict[str, Any]] = []
    for rec in records:
        try:
            model = ExportRecord.model_validate(rec)
        except ValidationError as exc:
            raise ExportValidationError(f"Record {rec.get('id')} failed validation: {exc.errors()[0]['msg']}") from exc
        data = model.model_dump()
        # Defence in depth: anything that still looks like a secret is redacted at export time.
        counts: Counter[str] = Counter()
        data = redactor.redact_value(data, counts)
        validated.append(data)
    return validated


_CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value)
    # Prevent CSV/formula injection when opened in spreadsheet software.
    if text.startswith(_CSV_DANGEROUS):
        text = "'" + text
    return text


CSV_COLUMNS = [
    "id",
    "input",
    "expected_output",
    "expected_output_source",
    "actual_output",
    "category",
    "failure_type",
    "failure_evidence",
    "review_status",
    "confidence_score",
    "quality_score",
    "source_trace_id",
    "source_timestamp",
    "system_prompt",
    "messages",
    "metadata",
]


def render(records: list[dict[str, Any]], fmt: ExportFormat, manifest: dict[str, Any]) -> str:
    if fmt == "jsonl":
        return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
    if fmt == "json":
        return json.dumps({"manifest": manifest, "examples": records}, ensure_ascii=False, indent=2, sort_keys=True)
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for r in records:
            writer.writerow([_csv_safe(r.get(c)) for c in CSV_COLUMNS])
        return buf.getvalue()
    raise ExportValidationError(f"Unsupported export format: {fmt}")
