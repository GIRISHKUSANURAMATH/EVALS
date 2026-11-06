import csv
import io
import json
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.evaluation.exporters import ExportValidationError, example_to_record, render, validate_records
from app.evaluation.generator import (
    FailureView,
    GenerationConfig,
    TraceSnapshot,
    build_example,
    generate_examples,
    primary_failure,
)
from app.evaluation.llm import NoOpSuggester, OpenAICompatibleSuggester, get_suggester
from app.evaluation.scoring import WEIGHTS, ScoringInput, score_example


def snap(**kw):
    base = dict(
        id="t1",
        trace_key="k1",
        job_id="j1",
        input_text="How do I reset my password?",
        output_text="Go to settings.",
        system_prompt="Be helpful",
        context=[],
        start_time=datetime(2026, 1, 1),
        status="ok",
        is_complete=True,
        has_missing_response=False,
        duplicate_of_id=None,
        duplicate_score=0.0,
        duplicate_group_size=1,
        models=["gpt"],
        total_latency_ms=100.0,
        metadata={"app": "x"},
        focal_metadata={},
        failures=[],
    )
    base.update(kw)
    return TraceSnapshot(**base)


# ------------------------------------------------------------------ generator
def test_successful_trace_has_no_expected_output_without_evidence():
    ex = build_example(snap())
    assert ex.category == "correctness" and ex.failure_type is None
    assert ex.expected_output is None and ex.expected_output_source == "none"
    assert ex.actual_output == "Go to settings."
    assert "observed output only" in ex.expected_output_rationale


def test_positive_feedback_makes_candidate_reference_not_approved():
    ex = build_example(snap(focal_metadata={"user_feedback": {"value": "thumbs_up"}}))
    assert ex.expected_output == "Go to settings."
    assert ex.expected_output_source == "candidate"
    assert "requires validation" in ex.expected_output_rationale


def test_reference_from_log_metadata_is_candidate():
    ex = build_example(snap(metadata={"expected_output": "Use the reset link."}))
    assert ex.expected_output == "Use the reset link." and ex.expected_output_source == "candidate"


def test_failed_trace_category_and_evidence():
    ex = build_example(snap(output_text=None, status="failed", failures=[FailureView("timeout", "observed", "30s")]))
    assert ex.category == "latency" and ex.failure_type == "timeout" and ex.failure_evidence == "observed"
    assert ex.expected_output is None
    assert ex.confidence_score == 0.95
    assert ex.metadata["provenance"] == {"job_id": "j1", "trace_key": "k1", "trace_id": "t1"}


def test_primary_failure_prefers_observed_then_priority():
    pf = primary_failure(
        [
            FailureView("excessive_latency", "heuristic"),
            FailureView("repeated_failure", "observed"),
            FailureView("tool_call_failure", "observed"),
        ]
    )
    assert pf.failure_type == "tool_call_failure"
    assert primary_failure([]) is None


def test_generate_filters_duplicates_successes_categories_and_quality():
    snaps = [
        snap(id="a", trace_key="a"),
        snap(id="b", trace_key="b", duplicate_of_id="a", duplicate_score=1.0),
        snap(id="c", trace_key="c", failures=[FailureView("empty_response", "observed")], output_text=""),
        snap(id="d", trace_key="d", input_text="   "),
    ]
    all_ = generate_examples(snaps, GenerationConfig())
    assert {e.source_trace_id for e in all_} == {"a", "c"}
    assert all_[0].source_trace_id == "c"  # failures come first
    assert {e.source_trace_id for e in generate_examples(snaps, GenerationConfig(exclude_duplicates=False))} == {
        "a",
        "b",
        "c",
    }
    assert [e.source_trace_id for e in generate_examples(snaps, GenerationConfig(include_successful=False))] == ["c"]
    assert [e.source_trace_id for e in generate_examples(snaps, GenerationConfig(categories=["error_handling"]))] == [
        "c"
    ]
    assert generate_examples(snaps, GenerationConfig(min_quality=0.99)) == []
    assert len(generate_examples(snaps, GenerationConfig(max_examples=1))) == 1


def test_llm_suggestion_is_marked_candidate():
    class Fake:
        name = "fake"

        def suggest(self, *_a):
            return "ideal answer"

    ex = build_example(snap(failures=[FailureView("empty_response", "observed")], output_text=""), Fake())
    assert ex.expected_output == "ideal answer" and ex.expected_output_source == "candidate"
    assert "fake" in ex.expected_output_rationale


# ------------------------------------------------------------------ scoring
def _si(**kw):
    base = dict(
        input_text="valid question here",
        actual_output="answer",
        expected_output=None,
        expected_output_source="none",
        failure_type=None,
        failure_evidence="none",
        has_metadata=True,
        duplicate_group_size=1,
        duplicate_score=0.0,
        is_duplicate=False,
        trace_complete=True,
        missing_response=False,
        confidence=0.5,
        review_status="pending",
    )
    base.update(kw)
    return ScoringInput(**base)


def test_score_is_explainable_and_weighted():
    score, factors = score_example(_si())
    assert {f["name"] for f in factors} == set(WEIGHTS)
    assert all(0 <= f["value"] <= 1 and f["explanation"] for f in factors)
    expected = sum(f["value"] * f["weight"] for f in factors) / sum(WEIGHTS.values())
    assert score == pytest.approx(expected, abs=1e-4)


def test_score_ordering():
    approved, _ = score_example(_si(review_status="approved", expected_output="x"))
    pending, _ = score_example(_si())
    dup, _ = score_example(_si(is_duplicate=True, duplicate_score=0.97))
    empty, _ = score_example(_si(input_text=""))
    rejected, _ = score_example(_si(review_status="rejected"))
    assert approved > pending > dup
    assert pending > empty
    assert pending > rejected


def test_observed_failure_is_a_valid_negative_example():
    _, factors = score_example(_si(failure_type="timeout", failure_evidence="observed", actual_output=None))
    ov = next(f for f in factors if f["name"] == "output_validity")
    assert ov["value"] == 1.0 and "negative example" in ov["explanation"]
    _, hf = score_example(_si(failure_type="refusal", failure_evidence="heuristic"))
    assert next(f for f in hf if f["name"] == "output_validity")["value"] == 0.6


# ------------------------------------------------------------------ export
def _ex(**kw):
    base = dict(
        id="e1",
        input="=cmd|' /C calc'!A0",
        expected_output=None,
        expected_output_source="none",
        actual_output="out",
        category="correctness",
        failure_type=None,
        failure_evidence="none",
        review_status="approved",
        confidence_score=0.5,
        quality_score=0.8,
        source_trace_key="k1",
        source_timestamp=datetime(2026, 1, 1),
        system_prompt="sys",
        context=[{"role": "user", "content": "earlier"}],
        metadata_={"a": 1},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_record_has_chat_messages():
    rec = example_to_record(_ex())
    assert rec["messages"][0] == {"role": "system", "content": "sys"}
    assert rec["messages"][-1]["role"] == "user"
    assert rec["source_timestamp"] == "2026-01-01T00:00:00"


def test_render_formats_roundtrip():
    recs = validate_records([example_to_record(_ex())])
    jl = render(recs, "jsonl", {})
    assert json.loads(jl.splitlines()[0])["id"] == "e1"
    js = json.loads(render(recs, "json", {"dataset_id": "d"}))
    assert js["manifest"]["dataset_id"] == "d" and len(js["examples"]) == 1
    rows = list(csv.DictReader(io.StringIO(render(recs, "csv", {}))))
    assert rows[0]["id"] == "e1"
    assert rows[0]["input"].startswith("'=")  # CSV formula injection neutralised
    assert json.loads(rows[0]["metadata"]) == {"a": 1}


def test_export_validation_rejects_bad_records():
    with pytest.raises(ExportValidationError):
        validate_records([example_to_record(_ex(review_status="bogus"))])
    with pytest.raises(ExportValidationError):
        render([], "xml", {})  # type: ignore[arg-type]


def test_export_redacts_any_leftover_secrets():
    rec = validate_records([example_to_record(_ex(actual_output="key sk-abcdefghijklmnopqrstuvwxyz"))])[0]
    assert "sk-abc" not in rec["actual_output"]


# ------------------------------------------------------------------ optional LLM interface
def test_noop_suggester_default():
    assert isinstance(get_suggester("none"), NoOpSuggester)
    assert NoOpSuggester().suggest("x", None, None) is None


def test_openai_compatible_suggester_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "m" and request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Reference answer"}}]})

    s = OpenAICompatibleSuggester("http://llm.local/v1", "m", "k", transport=httpx.MockTransport(handler))
    assert s.suggest("q", None, None) == "Reference answer"

    unsure = OpenAICompatibleSuggester(
        "http://x",
        "m",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "UNSURE"}}]})
        ),
    )
    assert unsure.suggest("q", None, None) is None
    failing = OpenAICompatibleSuggester("http://x", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert failing.suggest("q", None, None) is None
