from datetime import datetime

from app.ingestion.normalizer import normalize_record
from app.processing.clustering import ClusteringConfig, ClusterItem, cluster_items
from app.processing.dedup import DedupConfig, DedupItem, deduplicate
from app.processing.embeddings import semantic_vectors
from app.processing.failures import (
    HEURISTIC,
    OBSERVED,
    DetectionConfig,
    detect_failures,
    repetition_score,
    trace_status,
)
from app.processing.reconstruction import reconstruct_traces
from app.processing.text import normalize_text


def R(line, **kw):
    return normalize_record(kw, line)


# ------------------------------------------------------------------ reconstruction
def test_multi_turn_grouping_and_timestamp_ordering():
    recs = [
        R(1, trace_id="c", timestamp="2026-01-01T00:00:10Z", user_input="second", assistant_response="b"),
        R(2, trace_id="c", timestamp="2026-01-01T00:00:00Z", user_input="first", assistant_response="a"),
        R(3, trace_id="d", user_input="solo", assistant_response="x"),
        R(4, user_input="no trace", assistant_response="y"),
    ]
    traces = {t.trace_key: t for t in reconstruct_traces(recs)}
    assert [t.user_input for t in traces["c"].turns] == ["first", "second"]
    assert traces["c"].start_time == datetime(2026, 1, 1, 0, 0, 0)
    assert "line-4" in traces
    assert all(t.is_complete for t in traces.values())


def test_request_response_pairing_and_missing_response():
    recs = [
        R(1, trace_id="s", request_id="r1", user_input="q1", status="ok"),
        R(2, trace_id="s", request_id="r1", assistant_response="a1", latency_ms=5, status="ok"),
        R(3, trace_id="m", request_id="r2", user_input="q2", status="ok"),
    ]
    traces = {t.trace_key: t for t in reconstruct_traces(recs)}
    s = traces["s"]
    assert len(s.turns) == 1
    assert s.turns[0].assistant_response == "a1" and s.turns[0].line_numbers == [1, 2]
    assert s.is_complete
    m = traces["m"]
    assert m.has_missing_response and not m.is_complete


def test_invalid_records_skipped():
    recs = [R(1, trace_id="x", metadata={"a": 1}), R(2, trace_id="y", input="ok", output="ok")]
    assert [t.trace_key for t in reconstruct_traces(recs)] == ["y"]


def test_context_before_focus():
    recs = [R(i, trace_id="c", user_input=f"u{i}", assistant_response=f"a{i}") for i in range(1, 4)]
    tr = reconstruct_traces(recs)[0]
    tr.focal_turn = 2
    assert tr.context_before_focus() == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
    ]


# ------------------------------------------------------------------ failure detection
def _detect(*records, **cfg):
    traces = reconstruct_traces(list(records))
    res = detect_failures(traces, DetectionConfig(**cfg))
    return traces, res


def _types(res, key):
    return {(f.failure_type, f.evidence) for f in res[key]}


def test_observed_failures():
    traces, res = _detect(
        R(1, trace_id="e", user_input="q", status="error", error="Boom"),
        R(2, trace_id="t", user_input="q", status="timeout"),
        R(3, trace_id="em", user_input="q", assistant_response="   "),
        R(4, trace_id="tool", user_input="q", assistant_response="sorry", metadata={"tool_errors": ["ERROR: x"]}),
        R(
            5,
            trace_id="fb",
            user_input="q",
            assistant_response="a",
            metadata={"user_feedback": {"value": "thumbs_down", "comment": "made up facts"}},
        ),
        R(6, trace_id="neg", user_input="q", assistant_response="a", metadata={"rating": 1}),
        R(7, trace_id="trunc", user_input="q", assistant_response="a", metadata={"finish_reason": "length"}),
    )
    assert ("application_error", OBSERVED) in _types(res, "e")
    assert ("timeout", OBSERVED) in _types(res, "t")
    assert ("empty_response", OBSERVED) in _types(res, "em")
    assert ("tool_call_failure", OBSERVED) in _types(res, "tool")
    assert ("hallucination_candidate", OBSERVED) in _types(res, "fb")
    assert ("negative_feedback", OBSERVED) in _types(res, "neg")
    assert ("hallucination_candidate", OBSERVED) not in _types(res, "neg")
    assert ("truncated_output", OBSERVED) in _types(res, "trunc")


def test_errored_request_with_empty_response_is_not_double_counted():
    _, res = _detect(R(1, trace_id="e", user_input="q", assistant_response="", status="error", error_type="X"))
    assert {f.failure_type for f in res["e"]} == {"application_error"}


def test_malformed_json_only_when_json_requested():
    sys_json = "Respond with JSON only."
    _, res = _detect(
        R(1, trace_id="bad", system_prompt=sys_json, user_input="q", assistant_response="Sure! here you go"),
        R(2, trace_id="good", system_prompt=sys_json, user_input="q", assistant_response='```json\n{"a": 1}\n```'),
        R(3, trace_id="plain", system_prompt="Be helpful", user_input="q", assistant_response="Sure!"),
        R(
            4,
            trace_id="fmt",
            user_input="q",
            assistant_response="nope",
            metadata={"response_format": {"type": "json_object"}},
        ),
    )
    assert ("malformed_structured_output", OBSERVED) in _types(res, "bad")
    assert not res["good"]
    assert not res["plain"]
    assert ("malformed_structured_output", OBSERVED) in _types(res, "fmt")


def test_heuristic_failures_are_labelled_heuristic():
    _, res = _detect(
        R(1, trace_id="slow", user_input="question", assistant_response="ok", latency_ms=20_000),
        R(2, trace_id="rep", user_input="question", assistant_response="the total is ten dollars. " * 20),
        R(3, trace_id="ref", user_input="question", assistant_response="I'm sorry, but I can't help with that."),
        R(4, trace_id="edge", user_input="!!!! ???? 1234", assistant_response="ok"),
        latency_threshold_ms=10_000,
    )
    assert ("excessive_latency", HEURISTIC) in _types(res, "slow")
    assert ("repetitive_output", HEURISTIC) in _types(res, "rep")
    assert ("refusal", HEURISTIC) in _types(res, "ref")
    assert ("edge_case_input", HEURISTIC) in _types(res, "edge")


def test_successful_answer_is_never_labelled_incorrect():
    _, res = _detect(R(1, trace_id="ok", user_input="What is 2+2?", assistant_response="5"))
    assert res["ok"] == []  # no evidence -> no label, even if the answer looks wrong


def test_repeated_failures_and_canned_responses():
    recs = [R(i, trace_id=f"f{i}", user_input="Same failing input", status="error", error="x") for i in range(3)]
    recs += [
        R(10 + i, trace_id=f"c{i}", user_input=f"distinct question {i}", assistant_response="Please contact support.")
        for i in range(5)
    ]
    _, res = _detect(*recs)
    assert all(("repeated_failure", OBSERVED) in _types(res, f"f{i}") for i in range(3))
    assert all(("canned_response", HEURISTIC) in _types(res, f"c{i}") for i in range(5))


def test_focal_turn_points_at_first_failure():
    traces, _ = _detect(
        R(1, trace_id="c", user_input="a", assistant_response="fine"),
        R(2, trace_id="c", user_input="b", status="error", error="x"),
        R(3, trace_id="c", user_input="c", assistant_response="fine"),
    )
    assert traces[0].focal_turn == 1


def test_trace_status_levels():
    _, res = _detect(
        R(1, trace_id="f", user_input="q", status="error", error="x"),
        R(2, trace_id="w", user_input="question", assistant_response="ok", latency_ms=99_999),
        R(3, trace_id="o", user_input="question", assistant_response="ok"),
    )
    assert trace_status(res["f"]) == "failed"
    assert trace_status(res["w"]) == "warning"
    assert trace_status(res["o"]) == "ok"


def test_repetition_score():
    assert repetition_score("short text") == 0.0
    assert repetition_score("a b c d " * 20) > 0.8


# ------------------------------------------------------------------ dedup
def test_exact_normalized_and_semantic_duplicates():
    items = [
        DedupItem("a", "How do I reset my password?"),
        DedupItem("b", "How do I reset my password?"),
        DedupItem("c", "how do i reset my password"),
        DedupItem("d", "How do I reset my passwords?"),
        DedupItem("e", "What regions do you support?"),
    ]
    res, backend = deduplicate(items, DedupConfig(similarity_threshold=0.85))
    assert backend == "tfidf-char"
    assert res["a"].duplicate_of is None and res["a"].group_size == 4
    assert res["b"].method == "exact" and res["b"].duplicate_of == "a"
    assert res["c"].method == "normalized"
    assert res["d"].method == "semantic" and 0.85 <= res["d"].score <= 1.0
    assert res["e"].duplicate_of is None and res["e"].group_size == 1


def test_threshold_controls_semantic_matching():
    items = [DedupItem("a", "reset my password please"), DedupItem("b", "reset my password now please")]
    strict, _ = deduplicate(items, DedupConfig(similarity_threshold=0.99))
    loose, _ = deduplicate(items, DedupConfig(similarity_threshold=0.6))
    assert strict["b"].duplicate_of is None
    assert loose["b"].duplicate_of == "a"


def test_priority_chooses_representative():
    items = [DedupItem("a", "same"), DedupItem("b", "same", priority=1)]
    res, _ = deduplicate(items)
    assert res["b"].duplicate_of is None and res["a"].duplicate_of == "b"


def test_dedup_works_without_semantic_and_empty_input():
    assert deduplicate([]) == ({}, "none")
    res, backend = deduplicate([DedupItem("a", "x y"), DedupItem("b", "x  y!")], DedupConfig(use_semantic=False))
    assert backend == "disabled" and res["b"].method == "normalized"


def test_embedding_fallback_to_tfidf_when_unavailable():
    _, backend = semantic_vectors(["a b", "c d"], use_embeddings=True, model_name="does/not-exist")
    assert backend == "tfidf-char"


def test_normalize_text():
    assert normalize_text("Hello,   WORLD!! [REDACTED_EMAIL]") == "hello world redacted"
    assert normalize_text(None) == ""


# ------------------------------------------------------------------ clustering
def _cluster_items():
    billing = [
        "refund my invoice payment",
        "invoice payment failed card",
        "billing invoice charged twice",
        "payment card declined invoice",
    ]
    auth = ["reset password login", "cannot login password reset", "two factor login code", "login locked password"]
    return [ClusterItem(f"b{i}", t, failed=i == 0) for i, t in enumerate(billing)] + [
        ClusterItem(f"a{i}", t) for i, t in enumerate(auth)
    ]


def test_kmeans_separates_topics():
    res = cluster_items(_cluster_items(), ClusteringConfig(n_clusters=2))
    assert len(res) == 2
    groups = [set(k[0] for k in c.member_keys) for c in res]
    assert {"b"} in groups and {"a"} in groups
    billing = next(c for c in res if c.member_keys[0].startswith("b"))
    assert billing.failure_rate == 0.25
    assert billing.representative_key in billing.member_keys
    assert billing.top_terms and billing.label


def test_auto_k_and_dbscan():
    auto = cluster_items(_cluster_items())
    assert 2 <= len(auto) <= 4
    db = cluster_items(_cluster_items(), ClusteringConfig(method="dbscan", dbscan_eps=0.9, dbscan_min_samples=2))
    assert sum(len(c.member_keys) for c in db) == 8
    assert all(c.method == "dbscan" for c in db)


def test_clustering_small_and_empty_inputs():
    assert cluster_items([]) == []
    assert cluster_items([ClusterItem("x", "   ")]) == []
    small = cluster_items([ClusterItem("x", "hello world"), ClusterItem("y", "foo bar")])
    assert len(small) == 1 and small[0].label == "all"
