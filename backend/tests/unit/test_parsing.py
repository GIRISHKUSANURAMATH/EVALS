import json

import pytest

from app.ingestion.normalizer import normalize_record, normalize_status, parse_timestamp
from app.ingestion.parsers import parse_content, parse_csv, parse_json, parse_jsonl, parse_log
from app.ingestion.validation import UploadValidationError, detect_format, validate_upload


def test_jsonl_parses_valid_and_reports_malformed_lines():
    text = "\n".join(
        [
            json.dumps({"trace_id": "a", "user_input": "hi", "assistant_response": "hello"}),
            "{not json",
            "",
            json.dumps([1, 2]),
            json.dumps({"trace_id": "b", "prompt": "q", "completion": "a"}),
        ]
    )
    res = parse_jsonl(text, 100)
    assert len(res.records) == 2
    assert {ln for ln, _ in res.malformed} == {2, 4}
    assert res.records[1].user_input == "q" and res.records[1].assistant_response == "a"
    assert res.total_lines == 4


def test_jsonl_all_invalid_raises():
    with pytest.raises(UploadValidationError):
        parse_jsonl("garbage\nmore garbage", 100)


def test_json_array_and_wrapped_object():
    arr = parse_json(json.dumps([{"input": "x", "output": "y"}]), 10)
    assert arr.records[0].user_input == "x"
    wrapped = parse_json(json.dumps({"logs": [{"input": "x"}, {"input": "z"}]}), 10)
    assert len(wrapped.records) == 2
    single = parse_json(json.dumps({"input": "solo", "output": "o"}), 10)
    assert len(single.records) == 1


def test_json_malformed_raises():
    with pytest.raises(UploadValidationError, match="Malformed JSON"):
        parse_json('{"a": ', 10)


def test_csv_parsing_with_json_cells_and_empty_response():
    text = 'timestamp,session_id,prompt,completion,metadata\n2026-01-01T00:00:00Z,s1,hello,,"{""k"": 1}"\n'
    res = parse_csv(text, 10)
    rec = res.records[0]
    assert rec.trace_id == "s1"
    assert rec.assistant_response == ""  # explicit empty, not missing
    assert rec.metadata["k"] == 1


def test_csv_malformed_raises():
    with pytest.raises(UploadValidationError):
        parse_csv("only_one_column\nvalue\n", 10)
    with pytest.raises(UploadValidationError):
        parse_csv('a,b\n1,2,3,4\n"unterminated', 10)


def test_logfmt_parsing():
    text = (
        '2026-01-01T10:00:00Z INFO trace_id=t1 user_input="hello there" assistant_response="hi" latency_ms=120\n'
        '2026-01-01T10:00:01Z ERROR trace_id=t2 user_input="x" error_message="boom"\n'
        "no pairs here\n"
    )
    res = parse_log(text, 10)
    assert len(res.records) == 2
    assert res.records[0].user_input == "hello there"
    assert res.records[0].latency_ms == 120
    assert res.records[1].status == "error"
    assert res.malformed[0][0] == 3


def test_record_limit_enforced():
    text = "\n".join(json.dumps({"input": str(i)}) for i in range(5))
    with pytest.raises(UploadValidationError, match="maximum"):
        parse_content(text, "jsonl", limit=3)


def test_openai_nested_request_response():
    rec = normalize_record(
        {
            "request": {
                "model": "gpt-4o",
                "user": "user-123",
                "messages": [
                    {"role": "system", "content": "be nice"},
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "first answer"},
                    {"role": "user", "content": [{"type": "text", "text": "second"}]},
                ],
            },
            "response": {
                "choices": [{"message": {"content": "second answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        },
        1,
    )
    assert rec.system_prompt == "be nice"
    assert rec.user_input == "second"  # the 'user' id field must not be mistaken for input
    assert rec.assistant_response == "second answer"
    assert rec.total_tokens == 15
    assert rec.metadata["context"][0] == {"role": "user", "content": "first"}


def test_normalizer_error_dict_and_status_codes():
    rec = normalize_record({"input": "x", "error": {"type": "RateLimit", "message": "429"}}, 1)
    assert rec.status == "error" and rec.error_type == "RateLimit"
    assert normalize_status(None, 504, False) == "timeout"
    assert normalize_status("TIMEOUT", None, False) == "timeout"
    assert normalize_status("200", None, False) == "ok"
    assert normalize_status(None, 500, False) == "error"


def test_record_without_content_is_invalid():
    rec = normalize_record({"trace_id": "t", "metadata": {"a": 1}}, 7)
    assert not rec.is_valid
    assert rec.validation_errors


def test_negative_latency_and_bad_timestamp_flagged():
    rec = normalize_record({"input": "x", "latency_ms": -5, "timestamp": "not a date"}, 1)
    assert rec.latency_ms is None
    assert "negative latency" in rec.validation_errors
    assert "unparseable timestamp" in rec.validation_errors


def test_latency_seconds_converted():
    assert normalize_record({"input": "x", "latency_s": 1.5}, 1).latency_ms == 1500


@pytest.mark.parametrize(
    "value,expected_year",
    [("2026-03-01T10:00:00Z", 2026), (1767225600, 2026), (1767225600000, 2026), ("2026-03-01 10:00:00+05:30", 2026)],
)
def test_parse_timestamp_formats(value, expected_year):
    assert parse_timestamp(value).year == expected_year


def test_unknown_keys_preserved_in_metadata():
    rec = normalize_record({"input": "x", "customer_tier": "gold"}, 1)
    assert rec.metadata["customer_tier"] == "gold"


def test_detect_format():
    assert detect_format("a.jsonl", "") == "jsonl"
    assert detect_format("a.log", '{"a": 1}') == "jsonl"
    assert detect_format("a.log", "k=v") == "log"
    with pytest.raises(UploadValidationError):
        detect_format("a.exe", "")


def test_validate_upload_rules():
    with pytest.raises(UploadValidationError, match="empty"):
        validate_upload("a.jsonl", b"", 100)
    with pytest.raises(UploadValidationError, match="maximum"):
        validate_upload("a.jsonl", b"x" * 101, 100)
    with pytest.raises(UploadValidationError, match="Unsupported"):
        validate_upload("a.exe", b"abc", 100)
    with pytest.raises(UploadValidationError, match="binary"):
        validate_upload("a.jsonl", b"ab\x00cd", 100)
    with pytest.raises(UploadValidationError, match="binary"):
        validate_upload("a.csv", b"PK\x03\x04rest", 100)
    with pytest.raises(UploadValidationError, match="UTF-8"):
        validate_upload("a.csv", b"\xff\xfe\xfa", 100)
    ok = validate_upload("a.csv", "﻿a,b\n1,2".encode(), 100)
    assert ok.text.startswith("a,b")
