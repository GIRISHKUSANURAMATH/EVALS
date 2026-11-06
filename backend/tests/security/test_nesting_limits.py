"""Regression tests: deeply nested JSON must be rejected cleanly, never crash the request.

Before the fix, a JSON document nested ~2000 levels raised RecursionError inside json.loads,
and records nested ~500 levels parsed but crashed later pipeline stages; both returned HTTP 500.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ingestion.parsers import MAX_NESTING_DEPTH, parse_json, parse_jsonl
from app.ingestion.validation import UploadValidationError


def nested_metadata_record(depth: int) -> str:
    return '{"input": "hi", "output": "yo", "metadata": ' + '{"a": ' * depth + "1" + "}" * depth + "}"


def test_limit_is_generous_for_real_logs() -> None:
    assert MAX_NESTING_DEPTH >= 32


def test_json_document_too_deep_for_the_parser_is_a_validation_error() -> None:
    doc = "[" * 5000 + "]" * 5000
    with pytest.raises(UploadValidationError, match="nested"):
        parse_json(doc, limit=100)


def test_record_nested_beyond_limit_is_reported_as_malformed_not_parsed() -> None:
    ok = nested_metadata_record(5)
    deep = nested_metadata_record(MAX_NESTING_DEPTH + 5)
    result = parse_json(f"[{ok}, {deep}]", limit=100)
    assert len(result.records) == 1
    assert result.malformed and "nested" in result.malformed[0][1]


def test_jsonl_deep_line_is_malformed_and_other_lines_survive() -> None:
    text = "\n".join(
        ['{"input": "a", "output": "b"}', "[" * 5000 + "]" * 5000, nested_metadata_record(MAX_NESTING_DEPTH + 5)]
    )
    result = parse_jsonl(text, limit=100)
    assert len(result.records) == 1
    assert [line for line, _ in result.malformed] == [2, 3]
    assert all("nested" in reason for _, reason in result.malformed)


def test_upload_of_deep_json_document_returns_422(client: TestClient) -> None:
    r = client.post("/api/v1/ingestion/upload", files={"file": ("deep.json", b"[" * 3000 + b"]" * 3000)})
    assert r.status_code == 422, r.text
    assert "nested" in r.json()["detail"]


def test_upload_with_deep_metadata_skips_only_that_record(client: TestClient) -> None:
    body = "\n".join(['{"trace_id": "t1", "input": "hello", "output": "hi"}', nested_metadata_record(500)])
    r = client.post("/api/v1/ingestion/upload", files={"file": ("deep.jsonl", body.encode())})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "completed"
    assert job["valid_records"] == 1
    assert job["invalid_records"] == 1
