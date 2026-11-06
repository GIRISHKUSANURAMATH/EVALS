"""Turn processed traces into candidate evaluation examples.

Key rule: production logs contain what the model *said*, not what it *should have said*.
So ``expected_output`` is only filled when there is a defensible source, and even then it
is marked ``candidate`` until a human approves it:

* ``none``           - no reference available (the common case, especially for failures)
* ``candidate``      - from a reference field in the source log, from a production answer
                       that received explicit positive user feedback, or from an optional
                       LLM suggester. Requires validation.
* ``human_approved`` - set only through the review workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.evaluation.categories import FAILURE_PRIORITY, FAILURE_TO_CATEGORY
from app.evaluation.llm import ExpectedOutputSuggester, NoOpSuggester
from app.evaluation.scoring import ScoringInput, score_example

_REFERENCE_KEYS = ("expected_output", "reference_answer", "reference", "ground_truth", "gold_answer", "ideal_response")
_POSITIVE = {"thumbs_up", "positive", "up", "good", "1", "true"}


@dataclass
class FailureView:
    failure_type: str
    evidence: str
    detail: str = ""


@dataclass
class TraceSnapshot:
    id: str
    trace_key: str
    job_id: str
    input_text: str
    output_text: str | None
    system_prompt: str | None
    context: list[dict[str, Any]]
    start_time: datetime | None
    status: str
    is_complete: bool
    has_missing_response: bool
    duplicate_of_id: str | None
    duplicate_score: float
    duplicate_group_size: int
    models: list[str]
    total_latency_ms: float | None
    metadata: dict[str, Any]
    focal_metadata: dict[str, Any]
    failures: list[FailureView] = field(default_factory=list)
    cluster_label: str | None = None


@dataclass
class GenerationConfig:
    include_successful: bool = True
    exclude_duplicates: bool = True
    categories: list[str] | None = None
    min_quality: float = 0.0
    max_examples: int = 5000


@dataclass
class ExampleDraft:
    source_trace_id: str
    source_trace_key: str
    source_job_id: str
    source_timestamp: datetime | None
    input: str
    system_prompt: str | None
    context: list[dict[str, Any]]
    actual_output: str | None
    expected_output: str | None
    expected_output_source: str
    expected_output_rationale: str
    category: str
    failure_type: str | None
    failure_evidence: str
    metadata: dict[str, Any]
    confidence_score: float
    quality_score: float
    quality_factors: list[dict[str, Any]]


def primary_failure(failures: list[FailureView]) -> FailureView | None:
    if not failures:
        return None
    order = {name: i for i, name in enumerate(FAILURE_PRIORITY)}
    return sorted(
        failures,
        key=lambda f: (0 if f.evidence == "observed" else 1, order.get(f.failure_type, len(order))),
    )[0]


def has_positive_feedback(meta: dict[str, Any]) -> bool:
    fb = meta.get("user_feedback", meta.get("feedback"))
    if isinstance(fb, dict):
        fb = fb.get("value", fb.get("score", fb.get("rating")))
    if fb is not None and str(fb).lower() in _POSITIVE:
        return True
    rating = meta.get("rating")
    try:
        return rating is not None and float(rating) >= 4
    except (TypeError, ValueError):
        return False


def _expected_output(
    snap: TraceSnapshot, pf: FailureView | None, suggester: ExpectedOutputSuggester
) -> tuple[str | None, str, str]:
    for source in (snap.focal_metadata, snap.metadata):
        for key in _REFERENCE_KEYS:
            val = source.get(key)
            if isinstance(val, str) and val.strip():
                return val, "candidate", f"Reference '{key}' found in the source log. Requires human validation."
    if pf is None and snap.output_text and has_positive_feedback(snap.focal_metadata):
        return (
            snap.output_text,
            "candidate",
            "Production answer received explicit positive user feedback. Candidate reference; requires validation.",
        )
    suggestion = suggester.suggest(snap.input_text, snap.system_prompt, pf.failure_type if pf else None)
    if suggestion:
        return suggestion, "candidate", f"Suggested by LLM provider '{suggester.name}'. Requires human validation."
    if pf is not None:
        return (
            None,
            "none",
            f"No reference answer available. Production run failed ({pf.failure_type}); "
            "a reviewer must define the expected behaviour.",
        )
    return None, "none", "No reference answer available. The production output is recorded as observed output only."


def build_example(snap: TraceSnapshot, suggester: ExpectedOutputSuggester | None = None) -> ExampleDraft:
    suggester = suggester or NoOpSuggester()
    pf = primary_failure(snap.failures)
    if pf is not None:
        category = FAILURE_TO_CATEGORY.get(pf.failure_type, "edge_cases")
        confidence = 0.95 if pf.evidence == "observed" else 0.6
        failure_type, evidence = pf.failure_type, pf.evidence
    else:
        category, failure_type, evidence = "correctness", None, "none"
        confidence = 0.75 if has_positive_feedback(snap.focal_metadata) else 0.5

    expected, source, rationale = _expected_output(snap, pf, suggester)
    metadata: dict[str, Any] = {
        "models": snap.models,
        "latency_ms": snap.total_latency_ms,
        "trace_status": snap.status,
        "all_failures": [{"type": f.failure_type, "evidence": f.evidence, "detail": f.detail} for f in snap.failures],
        "duplicate_group_size": snap.duplicate_group_size,
        "cluster": snap.cluster_label,
        "provenance": {"job_id": snap.job_id, "trace_key": snap.trace_key, "trace_id": snap.id},
    }
    score, factors = score_example(
        ScoringInput(
            input_text=snap.input_text,
            actual_output=snap.output_text,
            expected_output=expected,
            expected_output_source=source,
            failure_type=failure_type,
            failure_evidence=evidence,
            has_metadata=bool(snap.models or snap.metadata),
            duplicate_group_size=snap.duplicate_group_size,
            duplicate_score=snap.duplicate_score,
            is_duplicate=snap.duplicate_of_id is not None,
            trace_complete=snap.is_complete,
            missing_response=snap.has_missing_response,
            confidence=confidence,
            review_status="pending",
        )
    )
    return ExampleDraft(
        source_trace_id=snap.id,
        source_trace_key=snap.trace_key,
        source_job_id=snap.job_id,
        source_timestamp=snap.start_time,
        input=snap.input_text,
        system_prompt=snap.system_prompt,
        context=snap.context,
        actual_output=snap.output_text,
        expected_output=expected,
        expected_output_source=source,
        expected_output_rationale=rationale,
        category=category,
        failure_type=failure_type,
        failure_evidence=evidence,
        metadata=metadata,
        confidence_score=confidence,
        quality_score=score,
        quality_factors=factors,
    )


def generate_examples(
    snapshots: list[TraceSnapshot], cfg: GenerationConfig, suggester: ExpectedOutputSuggester | None = None
) -> list[ExampleDraft]:
    drafts: list[ExampleDraft] = []
    # Failures first so the max_examples cap keeps the most informative examples.
    ordered = sorted(snapshots, key=lambda s: (0 if s.failures else 1, s.start_time or datetime.max, s.trace_key))
    for snap in ordered:
        if len(drafts) >= cfg.max_examples:
            break
        if cfg.exclude_duplicates and snap.duplicate_of_id is not None:
            continue
        if not snap.failures and not cfg.include_successful:
            continue
        if not snap.input_text.strip() and not snap.failures:
            continue
        draft = build_example(snap, suggester)
        if cfg.categories and draft.category not in cfg.categories:
            continue
        if draft.quality_score < cfg.min_quality:
            continue
        drafts.append(draft)
    return drafts
