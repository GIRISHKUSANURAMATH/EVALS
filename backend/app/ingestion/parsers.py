"""Format-specific parsers: JSONL, JSON, CSV and generic key=value application logs."""

from __future__ import annotations

import io
import json
import re
import shlex
from typing import Any

import pandas as pd

from app.ingestion.normalizer import ALIASES, normalize_record
from app.ingestion.schema import NormalizedRecord, ParseResult
from app.ingestion.validation import UploadValidationError

RESPONSE_COLUMNS = set(ALIASES["assistant_response"])
# Real log records nest a few levels; anything deeper is rejected before later (recursive)
# pipeline stages see it. Checked iteratively so the check itself cannot overflow the stack.
MAX_NESTING_DEPTH = 64
_TOO_DEEP = f"nested more than {MAX_NESTING_DEPTH} levels deep"
_LIST_KEYS = ("logs", "records", "data", "items", "events", "traces", "interactions")


def _exceeds_depth(obj: Any, limit: int = MAX_NESTING_DEPTH) -> bool:
    stack: list[tuple[Any, int]] = [(obj, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, dict):
            children: Any = value.values()
        elif isinstance(value, list):
            children = value
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def _collect(items: list[tuple[int, Any]], file_format: str, total: int, limit: int) -> ParseResult:
    records: list[NormalizedRecord] = []
    malformed: list[tuple[int, str]] = []
    for line_no, obj in items:
        if len(records) >= limit:
            raise UploadValidationError(f"File exceeds the maximum of {limit} records per upload.")
        if not isinstance(obj, dict):
            malformed.append((line_no, "record is not a JSON object"))
            continue
        if _exceeds_depth(obj):
            malformed.append((line_no, f"record is {_TOO_DEEP}"))
            continue
        records.append(normalize_record(obj, line_no))
    return ParseResult(file_format=file_format, records=records, total_lines=total, malformed=malformed)


def parse_jsonl(text: str, limit: int) -> ParseResult:
    items: list[tuple[int, Any]] = []
    malformed: list[tuple[int, str]] = []
    total = 0
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        total += 1
        try:
            items.append((i, json.loads(line)))
        except json.JSONDecodeError as exc:
            malformed.append((i, f"invalid JSON: {exc.msg}"))
        except RecursionError:
            malformed.append((i, f"invalid JSON: {_TOO_DEEP}"))
    if total > 0 and not items:
        raise UploadValidationError("No valid JSON lines found in file.")
    result = _collect(items, "jsonl", total, limit)
    result.malformed = malformed + result.malformed
    return result


def parse_json(text: str, limit: int) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UploadValidationError(f"Malformed JSON document: {exc.msg} at line {exc.lineno}.") from exc
    except RecursionError as exc:
        raise UploadValidationError(f"Malformed JSON document: {_TOO_DEEP}.") from exc
    if isinstance(data, dict):
        for key in _LIST_KEYS:
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise UploadValidationError("JSON document must be an array of records or an object containing one.")
    return _collect([(i, obj) for i, obj in enumerate(data, start=1)], "json", len(data), limit)


def parse_csv(text: str, limit: int) -> ParseResult:
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, on_bad_lines="error")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise UploadValidationError(f"Malformed CSV file: {str(exc).splitlines()[0]}") from exc
    if df.empty or len(df.columns) < 2:
        raise UploadValidationError("CSV file must have a header row and at least two columns.")
    items: list[tuple[int, Any]] = []
    for idx, row in enumerate(df.to_dict(orient="records"), start=2):  # line 1 is the header
        obj: dict[str, Any] = {}
        for k, v in row.items():
            if v == "":
                if k in RESPONSE_COLUMNS:
                    obj[str(k)] = ""  # keep explicit empty responses
                continue
            # Allow JSON-encoded cells for nested fields (e.g. metadata).
            if isinstance(v, str) and v[:1] in "{[" and k in ("metadata", "messages", "usage", "error"):
                try:
                    obj[str(k)] = json.loads(v)
                    continue
                except json.JSONDecodeError:
                    pass
            obj[str(k)] = v
        items.append((idx, obj))
    return _collect(items, "csv", len(items), limit)


_LOG_PREFIX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?\s*"
    r"(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)?\s*(?P<rest>.*)$"
)


def parse_log(text: str, limit: int) -> ParseResult:
    """Parse generic application logs in logfmt style:

    2024-05-01T10:00:00Z INFO trace_id=abc user_input="hello" assistant_response="hi" latency_ms=120
    """
    items: list[tuple[int, Any]] = []
    malformed: list[tuple[int, str]] = []
    total = 0
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        total += 1
        m = _LOG_PREFIX.match(line.strip())
        rest = m.group("rest") if m else line
        try:
            tokens = shlex.split(rest, posix=True)
        except ValueError:
            malformed.append((i, "unbalanced quotes"))
            continue
        obj: dict[str, Any] = {}
        for tok in tokens:
            if "=" in tok:
                k, v = tok.split("=", 1)
                obj[k.strip()] = v
        if not obj:
            malformed.append((i, "no key=value pairs found"))
            continue
        if m and m.group("ts") and "timestamp" not in obj:
            obj["timestamp"] = m.group("ts")
        if m and m.group("level"):
            obj.setdefault("level", m.group("level"))
            if m.group("level") in ("ERROR", "CRITICAL") and "status" not in obj:
                obj["status"] = "error"
        items.append((i, obj))
    if total > 0 and not items:
        raise UploadValidationError("No parseable key=value log lines found.")
    result = _collect(items, "log", total, limit)
    result.malformed = malformed + result.malformed
    return result


PARSERS = {"jsonl": parse_jsonl, "json": parse_json, "csv": parse_csv, "log": parse_log}


def parse_content(text: str, file_format: str, limit: int = 200_000) -> ParseResult:
    try:
        parser = PARSERS[file_format]
    except KeyError as exc:
        raise UploadValidationError(f"Unsupported format: {file_format}") from exc
    return parser(text, limit)
