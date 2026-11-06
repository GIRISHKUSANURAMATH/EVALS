"""Rebuild complete interactions (traces) from individual log records.

* Records sharing a trace id form one trace; records without one become single-turn traces.
* Request and response events logged as separate records are paired by request id.
* Turns are ordered by timestamp (falling back to file order).
* Missing responses and incomplete traces are flagged rather than silently dropped.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.ingestion.schema import NormalizedRecord

_TURN_META_KEYS = (
    "tool_calls",
    "tool_errors",
    "finish_reason",
    "response_format",
    "feedback",
    "user_feedback",
    "rating",
    "tags",
)


@dataclass
class Turn:
    index: int
    line_numbers: list[int]
    request_id: str | None
    timestamp: datetime | None
    user_input: str | None
    assistant_response: str | None
    model: str | None
    latency_ms: float | None
    total_tokens: int | None
    status: str | None
    error_type: str | None
    error_message: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def missing_response(self) -> bool:
        return (
            bool(self.user_input)
            and self.assistant_response is None
            and self.status == "ok"
            and not (self.error_type or self.error_message)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "line_numbers": self.line_numbers,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_input": self.user_input,
            "assistant_response": self.assistant_response,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "total_tokens": self.total_tokens,
            "status": self.status,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


@dataclass
class ReconstructedTrace:
    trace_key: str
    turns: list[Turn]
    system_prompt: str | None
    record_lines: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)
    focal_turn: int = -1  # set after failure detection

    @property
    def start_time(self) -> datetime | None:
        times = [t.timestamp for t in self.turns if t.timestamp]
        return min(times) if times else None

    @property
    def end_time(self) -> datetime | None:
        times = [t.timestamp for t in self.turns if t.timestamp]
        return max(times) if times else None

    @property
    def has_missing_response(self) -> bool:
        return any(t.missing_response for t in self.turns)

    @property
    def is_complete(self) -> bool:
        return bool(self.turns) and any(t.user_input for t in self.turns) and not self.has_missing_response

    @property
    def total_latency_ms(self) -> float | None:
        vals = [t.latency_ms for t in self.turns if t.latency_ms is not None]
        return sum(vals) if vals else None

    @property
    def total_tokens(self) -> int | None:
        vals = [t.total_tokens for t in self.turns if t.total_tokens is not None]
        return sum(vals) if vals else None

    @property
    def models(self) -> list[str]:
        return sorted({t.model for t in self.turns if t.model})

    def focus(self) -> Turn:
        if not self.turns:
            raise ValueError("trace has no turns")
        idx = self.focal_turn if 0 <= self.focal_turn < len(self.turns) else len(self.turns) - 1
        return self.turns[idx]

    def context_before_focus(self) -> list[dict[str, Any]]:
        focal = self.focus().index
        ctx: list[dict[str, Any]] = []
        for t in self.turns:
            if t.index >= focal:
                break
            if t.user_input:
                ctx.append({"role": "user", "content": t.user_input})
            if t.assistant_response:
                ctx.append({"role": "assistant", "content": t.assistant_response})
        return ctx


def _sort_key(rec: NormalizedRecord) -> tuple[int, datetime, int]:
    return (0 if rec.timestamp else 1, rec.timestamp or datetime.min, rec.line_number)


def _merge_pair(records: list[NormalizedRecord]) -> list[NormalizedRecord]:
    """Pair request-only and response-only records that share a request id."""
    by_req: OrderedDict[str, list[NormalizedRecord]] = OrderedDict()
    singles: list[NormalizedRecord] = []
    for rec in records:
        if rec.request_id:
            by_req.setdefault(rec.request_id, []).append(rec)
        else:
            singles.append(rec)
    merged: list[NormalizedRecord] = list(singles)
    for group in by_req.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=_sort_key)
        base = group[0]
        base.metadata = dict(base.metadata)
        base.metadata["_lines"] = [r.line_number for r in group]
        for other in group[1:]:
            for attr in (
                "user_input",
                "system_prompt",
                "assistant_response",
                "model",
                "latency_ms",
                "total_tokens",
                "error_type",
                "error_message",
            ):
                if getattr(base, attr) in (None, "") and getattr(other, attr) not in (None, ""):
                    setattr(base, attr, getattr(other, attr))
            if other.status and other.status != "ok":
                base.status = other.status
            for k, v in other.metadata.items():
                base.metadata.setdefault(k, v)
        merged.append(base)
    return merged


def reconstruct_traces(records: list[NormalizedRecord]) -> list[ReconstructedTrace]:
    groups: OrderedDict[str, list[NormalizedRecord]] = OrderedDict()
    for rec in records:
        if not rec.is_valid:
            continue
        key = rec.trace_id or (f"req-{rec.request_id}" if rec.request_id else f"line-{rec.line_number}")
        groups.setdefault(key, []).append(rec)

    traces: list[ReconstructedTrace] = []
    for key, recs in groups.items():
        recs = sorted(_merge_pair(recs), key=_sort_key)
        turns: list[Turn] = []
        system_prompt = next((r.system_prompt for r in recs if r.system_prompt), None)
        trace_meta: dict[str, Any] = {}
        for i, r in enumerate(recs):
            lines = r.metadata.pop("_lines", [r.line_number])
            turn_meta = {k: r.metadata[k] for k in _TURN_META_KEYS if k in r.metadata}
            turns.append(
                Turn(
                    index=i,
                    line_numbers=lines,
                    request_id=r.request_id,
                    timestamp=r.timestamp,
                    user_input=r.user_input,
                    assistant_response=r.assistant_response,
                    model=r.model,
                    latency_ms=r.latency_ms,
                    total_tokens=r.total_tokens,
                    status=r.status,
                    error_type=r.error_type,
                    error_message=r.error_message,
                    metadata=turn_meta,
                )
            )
            for k, v in r.metadata.items():
                if k not in _TURN_META_KEYS and k != "context":
                    trace_meta.setdefault(k, v)
        traces.append(
            ReconstructedTrace(
                trace_key=key,
                turns=turns,
                system_prompt=system_prompt,
                record_lines=[ln for t in turns for ln in t.line_numbers],
                metadata=trace_meta,
            )
        )
    return traces
