"""Explainable quality scoring.

The final score is a weighted average of named factors in [0, 1]. Each factor is
returned with its weight and a human-readable explanation so the UI can show *why*
an example scored the way it did.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WEIGHTS: dict[str, float] = {
    "completeness": 0.20,
    "duplicate_probability": 0.15,
    "input_validity": 0.15,
    "output_validity": 0.15,
    "trace_completeness": 0.10,
    "label_confidence": 0.15,
    "review_status": 0.10,
}

REVIEW_VALUES = {"approved": 1.0, "pending": 0.6, "flagged": 0.3, "rejected": 0.0}


@dataclass
class ScoringInput:
    input_text: str
    actual_output: str | None
    expected_output: str | None
    expected_output_source: str
    failure_type: str | None
    failure_evidence: str
    has_metadata: bool
    duplicate_group_size: int
    duplicate_score: float
    is_duplicate: bool
    trace_complete: bool
    missing_response: bool
    confidence: float
    review_status: str


def _factor(name: str, value: float, explanation: str) -> dict[str, Any]:
    value = round(max(0.0, min(1.0, value)), 3)
    return {"name": name, "value": value, "weight": WEIGHTS[name], "explanation": explanation}


def score_example(x: ScoringInput) -> tuple[float, list[dict[str, Any]]]:
    factors: list[dict[str, Any]] = []

    # Completeness: input, some observed outcome, provenance metadata, a reference answer.
    parts = {
        "input": bool(x.input_text.strip()),
        "outcome": bool(x.actual_output and x.actual_output.strip()) or x.failure_evidence == "observed",
        "metadata": x.has_metadata,
        "expected_output": x.expected_output is not None,
    }
    comp = 0.35 * parts["input"] + 0.3 * parts["outcome"] + 0.1 * parts["metadata"] + 0.25 * parts["expected_output"]
    missing = [k for k, v in parts.items() if not v]
    factors.append(
        _factor("completeness", comp, "all fields present" if not missing else f"missing: {', '.join(missing)}")
    )

    # Duplicate probability: duplicates add little evaluation value.
    if x.is_duplicate:
        dup = 1.0 - max(x.duplicate_score, 0.9)
        dup_expl = f"near-duplicate of another example (similarity {x.duplicate_score:.2f})"
    elif x.duplicate_group_size > 1:
        dup = 1.0
        dup_expl = f"representative of {x.duplicate_group_size} similar interactions"
    else:
        dup, dup_expl = 1.0, "no duplicates found"
    factors.append(_factor("duplicate_probability", dup, dup_expl))

    # Input validity.
    stripped = x.input_text.strip()
    if not stripped:
        iv, iv_expl = 0.0, "input is empty"
    elif stripped.replace("[REDACTED", "").strip("] _A-Z") == "":
        iv, iv_expl = 0.2, "input is almost entirely redacted"
    elif len(stripped) < 5:
        iv, iv_expl = 0.5, "input is very short"
    elif len(stripped) > 8000:
        iv, iv_expl = 0.7, "input is very long"
    else:
        iv, iv_expl = 1.0, "input looks well-formed"
    factors.append(_factor("input_validity", iv, iv_expl))

    # Output validity: for failure examples, an observed failure *is* the useful signal.
    if x.failure_type and x.failure_evidence == "observed":
        ov, ov_expl = 1.0, f"observed failure ({x.failure_type}) is a valid negative example"
    elif x.failure_type:
        ov, ov_expl = 0.6, f"heuristic signal ({x.failure_type}); needs confirmation"
    elif x.actual_output and x.actual_output.strip():
        ov, ov_expl = 1.0, "non-empty production output"
    else:
        ov, ov_expl = 0.3, "no usable production output"
    factors.append(_factor("output_validity", ov, ov_expl))

    if x.trace_complete:
        tc, tc_expl = 1.0, "trace is complete"
    elif x.missing_response:
        tc, tc_expl = 0.5, "trace has a missing response"
    else:
        tc, tc_expl = 0.4, "trace is incomplete"
    factors.append(_factor("trace_completeness", tc, tc_expl))

    factors.append(
        _factor(
            "label_confidence",
            x.confidence,
            {"observed": "label based on observed evidence", "heuristic": "label based on a heuristic"}.get(
                x.failure_evidence, "no failure label; category assigned by default"
            ),
        )
    )

    rv = REVIEW_VALUES.get(x.review_status, 0.5)
    factors.append(_factor("review_status", rv, f"review status: {x.review_status}"))

    total = sum(f["value"] * f["weight"] for f in factors) / sum(WEIGHTS.values())
    return round(total, 4), factors
