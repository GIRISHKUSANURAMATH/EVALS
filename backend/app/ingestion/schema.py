"""Canonical, format-independent representation of a single log record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedRecord:
    line_number: int
    trace_id: str | None = None
    request_id: str | None = None
    timestamp: datetime | None = None
    user_input: str | None = None
    system_prompt: str | None = None
    assistant_response: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    status: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    is_valid: bool = True
    validation_errors: list[str] = field(default_factory=list)
    redaction_count: int = 0
    raw_payload: str | None = None


@dataclass
class ParseResult:
    file_format: str
    records: list[NormalizedRecord]
    total_lines: int
    malformed: list[tuple[int, str]] = field(default_factory=list)  # (line, reason)

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.records if r.is_valid)

    @property
    def invalid_count(self) -> int:
        return len(self.malformed) + sum(1 for r in self.records if not r.is_valid)
