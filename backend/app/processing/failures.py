"""Failure and edge-case detection.

Each detected failure carries an ``evidence`` level:

* ``observed``  - directly recorded in the log (error status, error fields, empty/missing
                  response, timeout status, explicit negative user feedback, JSON that fails
                  to parse when JSON output was requested, a tool error message).
* ``heuristic`` - inferred from a rule of thumb (latency above a threshold, repetitive text,
                  canned identical answers, refusals, unusual inputs). These are *signals for
                  review*, not verdicts.

The detector never asserts that a model answer is factually wrong. A "hallucination
candidate" is only raised when the log itself contains user feedback saying so.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from app.processing.reconstruction import ReconstructedTrace, Turn
from app.processing.text import normalize_text

OBSERVED = "observed"
HEURISTIC = "heuristic"

FAILURE_TYPES: dict[str, str] = {
    "application_error": "The application recorded an error for this request.",
    "timeout": "The request timed out.",
    "empty_response": "The model returned an empty or whitespace-only response.",
    "missing_response": "A user request has no logged response and no error.",
    "malformed_structured_output": "JSON output was requested but the response is not valid JSON.",
    "tool_call_failure": "A tool call returned an error.",
    "negative_feedback": "The end user gave negative feedback on this response.",
    "hallucination_candidate": "User feedback flags this answer as fabricated/incorrect. Needs human verification.",
    "excessive_latency": "Latency exceeded the configured threshold.",
    "repetitive_output": "The response repeats the same phrase many times.",
    "canned_response": "The identical response was returned for many unrelated inputs.",
    "refusal": "The response looks like a refusal.",
    "repeated_failure": "The same input failed repeatedly across traces.",
    "edge_case_input": "Unusual input (very long, empty, or mostly non-text).",
    "truncated_output": "Generation stopped because of the token limit.",
}

SEVERITY = {
    "application_error": "high",
    "timeout": "high",
    "empty_response": "high",
    "missing_response": "medium",
    "malformed_structured_output": "high",
    "tool_call_failure": "high",
    "negative_feedback": "medium",
    "hallucination_candidate": "high",
    "excessive_latency": "low",
    "repetitive_output": "medium",
    "canned_response": "low",
    "refusal": "medium",
    "repeated_failure": "high",
    "edge_case_input": "low",
    "truncated_output": "medium",
}

_TIMEOUT_WORDS = re.compile(r"(?i)\b(time[d\s-]?out|deadline exceeded|timed out)\b")
_REFUSAL = re.compile(
    r"(?i)^\s*(i('m| am) sorry,? but|i can(no|')t (help|assist|provide|do)|i('m| am) (not able|unable) to|as an ai\b)"
)
_JSON_HINT = re.compile(r"(?i)\b(respond|reply|answer|output|return)\b[^.]{0,40}\bjson\b|\bjson (only|format|object)\b")
_HALLUCINATION_WORDS = ("hallucinat", "made up", "fabricat", "incorrect", "wrong", "not true", "false information")


@dataclass
class DetectionConfig:
    latency_threshold_ms: float = 10_000
    repeated_failure_min: int = 3
    canned_response_min_inputs: int = 5
    repetition_ratio: float = 0.5
    long_input_chars: int = 8_000


@dataclass
class DetectedFailure:
    failure_type: str
    evidence: str
    detail: str
    turn_index: int | None

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.failure_type, "medium")


def _expects_json(trace: ReconstructedTrace, turn: Turn) -> bool:
    fmt = turn.metadata.get("response_format")
    if isinstance(fmt, dict):
        fmt = fmt.get("type")
    if isinstance(fmt, str) and "json" in fmt.lower():
        return True
    return bool(trace.system_prompt and _JSON_HINT.search(trace.system_prompt))


def _parse_json_loose(text: str) -> bool:
    candidate = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", candidate)
    if fence:
        candidate = fence.group(1)
    try:
        json.loads(candidate)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def repetition_score(text: str, n: int = 4) -> float:
    """Fraction of word n-grams that are repeats. 0 = no repetition."""
    words = text.lower().split()
    if len(words) < n * 4:
        return 0.0
    grams = [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(grams)
    repeated = sum(c - 1 for c in counts.values() if c > 1)
    return repeated / len(grams)


def _feedback_signals(turn: Turn) -> tuple[bool, bool, str]:
    """Return (negative, hallucination, description) from explicit feedback fields."""
    fb = turn.metadata.get("user_feedback", turn.metadata.get("feedback"))
    rating = turn.metadata.get("rating")
    negative = False
    text = ""
    if isinstance(fb, dict):
        val = str(fb.get("value", fb.get("score", fb.get("rating", "")))).lower()
        text = str(fb.get("comment", fb.get("reason", "")))
        negative = val in ("thumbs_down", "negative", "down", "bad", "-1", "0", "false")
    elif isinstance(fb, str):
        text = fb
        negative = fb.lower() in ("thumbs_down", "negative", "down", "bad", "-1")
    if rating is not None:
        with contextlib.suppress(TypeError, ValueError):
            negative = negative or float(rating) <= 2
    tags = turn.metadata.get("tags")
    tag_text = " ".join(map(str, tags)) if isinstance(tags, list) else ""
    hallucination = negative and any(w in (text + " " + tag_text).lower() for w in _HALLUCINATION_WORDS)
    return negative, hallucination, text[:200]


def detect_turn_failures(trace: ReconstructedTrace, turn: Turn, cfg: DetectionConfig) -> list[DetectedFailure]:
    found: list[DetectedFailure] = []
    i = turn.index
    err_text = " ".join(filter(None, [turn.error_type, turn.error_message]))

    is_timeout = turn.status == "timeout" or bool(_TIMEOUT_WORDS.search(err_text))
    if is_timeout:
        found.append(DetectedFailure("timeout", OBSERVED, err_text[:300] or "status=timeout", i))
    elif turn.status == "error" or err_text:
        found.append(DetectedFailure("application_error", OBSERVED, err_text[:300] or f"status={turn.status}", i))

    tool_errors = turn.metadata.get("tool_errors")
    if tool_errors:
        found.append(DetectedFailure("tool_call_failure", OBSERVED, str(tool_errors[0])[:300], i))
    elif turn.error_type and "tool" in turn.error_type.lower():
        found.append(DetectedFailure("tool_call_failure", OBSERVED, err_text[:300], i))

    resp = turn.assistant_response
    has_tool_calls = bool(turn.metadata.get("tool_calls"))
    if turn.missing_response:
        found.append(DetectedFailure("missing_response", OBSERVED, "user input logged without a response", i))
    elif (
        resp is not None
        and not resp.strip()
        and not has_tool_calls
        and not is_timeout
        and not (turn.status == "error" or err_text)
    ):
        found.append(DetectedFailure("empty_response", OBSERVED, "response is empty", i))

    if resp and resp.strip():
        if _expects_json(trace, turn) and not _parse_json_loose(resp):
            found.append(DetectedFailure("malformed_structured_output", OBSERVED, "response failed JSON parsing", i))
        rep = repetition_score(resp)
        if rep >= cfg.repetition_ratio:
            found.append(DetectedFailure("repetitive_output", HEURISTIC, f"repetition ratio {rep:.2f}", i))
        if _REFUSAL.search(resp):
            found.append(DetectedFailure("refusal", HEURISTIC, resp[:120], i))

    if turn.metadata.get("finish_reason") == "length":
        found.append(DetectedFailure("truncated_output", OBSERVED, "finish_reason=length", i))

    if turn.latency_ms is not None and turn.latency_ms > cfg.latency_threshold_ms and not is_timeout:
        found.append(
            DetectedFailure(
                "excessive_latency",
                HEURISTIC,
                f"{turn.latency_ms:.0f} ms > {cfg.latency_threshold_ms:.0f} ms threshold",
                i,
            )
        )

    negative, hallucination, fb_text = _feedback_signals(turn)
    if hallucination:
        found.append(DetectedFailure("hallucination_candidate", OBSERVED, f"user feedback: {fb_text}", i))
    elif negative:
        found.append(DetectedFailure("negative_feedback", OBSERVED, f"user feedback: {fb_text}", i))

    ui = turn.user_input
    if ui is not None:
        stripped = ui.strip()
        alpha = sum(ch.isalpha() for ch in stripped)
        if len(stripped) > cfg.long_input_chars:
            found.append(DetectedFailure("edge_case_input", HEURISTIC, f"very long input ({len(stripped)} chars)", i))
        elif not stripped:
            found.append(DetectedFailure("edge_case_input", HEURISTIC, "empty user input", i))
        elif len(stripped) >= 5 and alpha / len(stripped) < 0.3:
            found.append(DetectedFailure("edge_case_input", HEURISTIC, "input is mostly non-alphabetic", i))
    return found


def detect_failures(
    traces: list[ReconstructedTrace], cfg: DetectionConfig | None = None
) -> dict[str, list[DetectedFailure]]:
    """Return failures keyed by trace_key. Also sets each trace's focal turn."""
    cfg = cfg or DetectionConfig()
    result: dict[str, list[DetectedFailure]] = {}
    for tr in traces:
        fails: list[DetectedFailure] = []
        for turn in tr.turns:
            fails.extend(detect_turn_failures(tr, turn, cfg))
        result[tr.trace_key] = fails

    # Cross-trace: repeated failures for the same normalized input.
    failing_inputs: dict[str, list[str]] = defaultdict(list)
    for tr in traces:
        observed = [f for f in result[tr.trace_key] if f.evidence == OBSERVED and f.failure_type != "negative_feedback"]
        for f in observed:
            failed_turn = tr.turns[f.turn_index] if f.turn_index is not None else None
            if failed_turn is not None and failed_turn.user_input:
                failing_inputs[normalize_text(failed_turn.user_input)].append(tr.trace_key)
                break
    for norm, keys in failing_inputs.items():
        unique = sorted(set(keys))
        if norm and len(unique) >= cfg.repeated_failure_min:
            for k in unique:
                first_turn = next((f.turn_index for f in result[k] if f.evidence == OBSERVED), None)
                result[k].append(
                    DetectedFailure(
                        "repeated_failure", OBSERVED, f"same input failed in {len(unique)} traces", first_turn
                    )
                )

    # Cross-trace: canned identical responses to many distinct inputs.
    resp_inputs: dict[str, set[str]] = defaultdict(set)
    resp_traces: dict[str, set[str]] = defaultdict(set)
    for tr in traces:
        for turn in tr.turns:
            if turn.assistant_response and len(turn.assistant_response.strip()) > 0 and turn.user_input:
                key = normalize_text(turn.assistant_response)
                resp_inputs[key].add(normalize_text(turn.user_input))
                resp_traces[key].add(tr.trace_key)
    by_key = {t.trace_key: t for t in traces}
    for key, inputs in resp_inputs.items():
        if key and len(inputs) >= cfg.canned_response_min_inputs:
            for k in sorted(resp_traces[key]):
                tr = by_key[k]
                idx = next(
                    t.index for t in tr.turns if t.assistant_response and normalize_text(t.assistant_response) == key
                )
                result[k].append(
                    DetectedFailure(
                        "canned_response", HEURISTIC, f"identical response for {len(inputs)} distinct inputs", idx
                    )
                )

    for tr in traces:
        fails = result[tr.trace_key]
        observed_turns = [f.turn_index for f in fails if f.evidence == OBSERVED and f.turn_index is not None]
        any_turns = [f.turn_index for f in fails if f.turn_index is not None]
        if observed_turns:
            tr.focal_turn = min(observed_turns)
        elif any_turns:
            tr.focal_turn = min(any_turns)
        else:
            tr.focal_turn = len(tr.turns) - 1
    return result


def trace_status(failures: list[DetectedFailure]) -> str:
    if any(f.evidence == OBSERVED and SEVERITY.get(f.failure_type) in ("high", "medium") for f in failures):
        return "failed"
    if failures:
        return "warning"
    return "ok"
