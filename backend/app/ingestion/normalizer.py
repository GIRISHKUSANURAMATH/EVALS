"""Map heterogeneous log dictionaries onto the canonical NormalizedRecord schema.

Handles flat application logs, OpenAI-style request/response payloads and chat
`messages` arrays. Unknown keys are preserved under `metadata`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.ingestion.schema import NormalizedRecord

ALIASES: dict[str, tuple[str, ...]] = {
    "trace_id": (
        "trace_id",
        "traceId",
        "trace",
        "conversation_id",
        "conversationId",
        "session_id",
        "sessionId",
        "thread_id",
    ),
    "request_id": ("request_id", "requestId", "span_id", "spanId", "id"),
    "timestamp": ("timestamp", "ts", "time", "@timestamp", "created_at", "createdAt", "created", "datetime", "date"),
    "user_input": ("user_input", "input", "prompt", "query", "question", "user_message", "request_text"),
    "system_prompt": ("system_prompt", "systemPrompt", "system", "instructions"),
    "assistant_response": (
        "assistant_response",
        "output",
        "response",
        "completion",
        "answer",
        "assistant_message",
        "response_text",
    ),
    "model": ("model", "model_name", "modelName", "engine"),
    "latency_ms": ("latency_ms", "latencyMs", "duration_ms", "elapsed_ms", "response_time_ms", "latency"),
    "latency_s": ("latency_s", "duration_s", "elapsed_s", "duration_seconds"),
    "prompt_tokens": ("prompt_tokens", "input_tokens", "promptTokens"),
    "completion_tokens": ("completion_tokens", "output_tokens", "completionTokens"),
    "total_tokens": ("total_tokens", "totalTokens", "tokens"),
    "status": ("status", "outcome", "result_status", "state"),
    "status_code": ("status_code", "statusCode", "http_status"),
    "error": ("error", "exception", "err"),
    "error_type": ("error_type", "errorType", "error_code", "exception_type"),
    "error_message": ("error_message", "errorMessage", "error_msg"),
    "metadata": ("metadata", "meta", "attributes", "extra", "tags"),
}

_CONSUMED: set[str] = {alias for aliases in ALIASES.values() for alias in aliases} | {
    "messages",
    "request",
    "response",
    "choices",
    "usage",
}

_OK_STATUSES = {"ok", "success", "succeeded", "completed", "complete", "200", "info"}
_ERROR_STATUSES = {"error", "failed", "failure", "exception", "fatal", "critical"}
_TIMEOUT_STATUSES = {"timeout", "timed_out", "timedout", "deadline_exceeded"}


def _first(data: dict[str, Any], key: str) -> Any:
    for alias in ALIASES[key]:
        if alias in data and data[alias] not in (None, ""):
            return data[alias]
    return None


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        # OpenAI content-parts format: [{"type": "text", "text": "..."}]
        parts = [p.get("text", "") for p in value if isinstance(p, dict) and "text" in p]
        if parts:
            return "\n".join(parts)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace(".", "", 1).isdigit()):
            num = float(value)
            if num > 1e12:  # epoch milliseconds
                num /= 1000.0
            return datetime.fromtimestamp(num, tz=UTC).replace(tzinfo=None)
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt
    except (ValueError, OverflowError, OSError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _extract_messages(messages: list[Any], rec: NormalizedRecord) -> None:
    """Fill fields from an OpenAI chat `messages` array."""
    context: list[dict[str, Any]] = []
    tool_calls: list[Any] = []
    tool_errors: list[str] = []
    last_user_idx = max(
        (i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "user"), default=-1
    )
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = _to_text(msg.get("content"))
        if role == "system" and rec.system_prompt is None:
            rec.system_prompt = content
        elif role == "user" and i == last_user_idx:
            rec.user_input = rec.user_input or content
        elif role == "assistant" and i > last_user_idx:
            if msg.get("tool_calls"):
                tool_calls.extend(msg["tool_calls"])
            if content:
                rec.assistant_response = rec.assistant_response or content
        elif role == "tool":
            if content and ("error" in content.lower() or msg.get("is_error")):
                tool_errors.append(content[:500])
            context.append({"role": "tool", "content": content})
        else:
            if role in ("user", "assistant"):
                context.append({"role": role, "content": content})
    if context:
        rec.metadata.setdefault("context", context)
    if tool_calls:
        rec.metadata.setdefault("tool_calls", tool_calls)
    if tool_errors:
        rec.metadata.setdefault("tool_errors", tool_errors)


def normalize_record(data: dict[str, Any], line_number: int) -> NormalizedRecord:
    rec = NormalizedRecord(line_number=line_number)

    # --- OpenAI-style nested request/response -----------------------------------------
    request = data.get("request") if isinstance(data.get("request"), dict) else None
    response = data.get("response") if isinstance(data.get("response"), dict) else None
    flat: dict[str, Any] = dict(data)
    if request is not None:
        flat.pop("request", None)
        for k, v in request.items():
            flat.setdefault(k, v)
    if response is not None:
        flat.pop("response", None)
        if "choices" in response:
            flat.setdefault("choices", response["choices"])
        if "usage" in response:
            flat.setdefault("usage", response["usage"])
        for k in ("model", "id", "created", "error", "status"):
            if k in response:
                flat.setdefault(k, response[k])

    if isinstance(flat.get("messages"), list):
        _extract_messages(flat["messages"], rec)

    choices = flat.get("choices")
    if isinstance(choices, list) and choices and rec.assistant_response is None:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") or {}
        if isinstance(message, dict):
            if message.get("tool_calls"):
                rec.metadata.setdefault("tool_calls", message["tool_calls"])
            rec.assistant_response = _to_text(message.get("content"))
        if rec.assistant_response is None and "text" in first:
            rec.assistant_response = _to_text(first.get("text"))
        if first.get("finish_reason"):
            rec.metadata.setdefault("finish_reason", first["finish_reason"])

    raw_usage = flat.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}

    # --- Flat fields --------------------------------------------------------------------
    rec.trace_id = _to_text(_first(flat, "trace_id"))
    rec.request_id = _to_text(_first(flat, "request_id"))
    raw_ts = _first(flat, "timestamp")
    rec.timestamp = parse_timestamp(raw_ts)
    if raw_ts is not None and rec.timestamp is None:
        rec.validation_errors.append("unparseable timestamp")
    if rec.user_input is None:
        rec.user_input = _to_text(_first(flat, "user_input"))
    if rec.system_prompt is None:
        rec.system_prompt = _to_text(_first(flat, "system_prompt"))
    if rec.assistant_response is None:
        raw_resp = _first(flat, "assistant_response")
        if raw_resp is None and any(flat.get(a) == "" for a in ALIASES["assistant_response"]):
            raw_resp = ""  # an explicitly logged empty response is not the same as a missing one
        rec.assistant_response = _to_text(raw_resp)
    rec.model = _to_text(_first(flat, "model"))

    latency = _to_float(_first(flat, "latency_ms"))
    if latency is None:
        secs = _to_float(_first(flat, "latency_s"))
        latency = secs * 1000.0 if secs is not None else None
    if latency is not None and latency < 0:
        rec.validation_errors.append("negative latency")
        latency = None
    rec.latency_ms = latency

    rec.prompt_tokens = _to_int(
        _first(flat, "prompt_tokens") or usage.get("prompt_tokens") or usage.get("input_tokens")
    )
    rec.completion_tokens = _to_int(
        _first(flat, "completion_tokens") or usage.get("completion_tokens") or usage.get("output_tokens")
    )
    rec.total_tokens = _to_int(_first(flat, "total_tokens") or usage.get("total_tokens"))
    if rec.total_tokens is None and rec.prompt_tokens is not None and rec.completion_tokens is not None:
        rec.total_tokens = rec.prompt_tokens + rec.completion_tokens

    # --- Errors and status ---------------------------------------------------------------
    err = _first(flat, "error")
    if isinstance(err, dict):
        rec.error_type = _to_text(err.get("type") or err.get("code"))
        rec.error_message = _to_text(err.get("message"))
    elif err is not None and err is not False:
        rec.error_message = _to_text(err)
    rec.error_type = rec.error_type or _to_text(_first(flat, "error_type"))
    rec.error_message = rec.error_message or _to_text(_first(flat, "error_message"))

    raw_status = _first(flat, "status")
    status_code = _to_int(_first(flat, "status_code"))
    rec.status = normalize_status(raw_status, status_code, has_error=bool(rec.error_type or rec.error_message))

    # --- Metadata ---------------------------------------------------------------------
    meta = _first(flat, "metadata")
    if isinstance(meta, dict):
        for k, v in meta.items():
            rec.metadata.setdefault(str(k), v)
    elif isinstance(meta, list):
        rec.metadata.setdefault("tags", meta)
    for key, value in flat.items():
        if key not in _CONSUMED and key not in rec.metadata:
            rec.metadata[key] = value

    if not (rec.user_input or rec.assistant_response or rec.error_message or rec.error_type):
        rec.is_valid = False
        rec.validation_errors.append("record has no user input, response or error information")
    return rec


def normalize_status(raw: Any, status_code: int | None, has_error: bool) -> str:
    text = str(raw).strip().lower() if raw is not None else ""
    if text.isdigit():
        status_code = status_code or int(text)
        text = ""
    if text in _TIMEOUT_STATUSES:
        return "timeout"
    if text in _ERROR_STATUSES:
        return "error"
    if status_code is not None:
        if status_code in (408, 504):
            return "timeout"
        if status_code >= 400:
            return "error"
    if has_error:
        return "error"
    if text in _OK_STATUSES or text == "" or status_code is not None:
        return "ok"
    return text[:32]
