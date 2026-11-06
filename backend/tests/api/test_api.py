import io
import json

from sqlalchemy import inspect

from app.database import session as db_session


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"


def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    for path in (
        "/api/v1/ingestion/upload",
        "/api/v1/datasets/generate",
        "/api/v1/exports/{dataset_id}",
        "/api/v1/examples/{example_id}/review",
        "/api/v1/dashboard/metrics",
    ):
        assert path in spec["paths"]


def test_migrations_create_all_tables(client):
    tables = set(inspect(db_session.engine).get_table_names())
    assert {
        "ingestion_jobs",
        "log_records",
        "traces",
        "failures",
        "clusters",
        "datasets",
        "dataset_versions",
        "eval_examples",
        "review_annotations",
        "processing_events",
        "categories",
        "app_settings",
        "alembic_version",
    } <= tables


def test_empty_dashboard_metrics(client):
    m = client.get("/api/v1/dashboard/metrics").json()
    assert m["total_logs"] == 0 and m["total_traces"] == 0
    assert m["processing_success_rate"] is None and m["average_latency_ms"] is None


def test_builtin_categories_seeded(client):
    names = {c["name"] for c in client.get("/api/v1/categories").json()}
    assert {"correctness", "hallucination", "tool_usage", "latency", "edge_cases"} <= names


def test_upload_jsonl_file(client):
    content = "\n".join(
        json.dumps(
            {"trace_id": f"t{i}", "user_input": f"q{i} a@b.com", "assistant_response": "a", "latency_ms": 100 + i}
        )
        for i in range(5)
    )
    r = client.post("/api/v1/ingestion/upload", files={"file": ("logs.jsonl", content, "application/json")})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "completed" and job["trace_count"] == 5 and job["valid_records"] == 5
    assert job["redaction_counts"]["email"] == 5
    stages = [e["stage"] for e in job["events"]]
    assert stages == [
        "validation",
        "parsing",
        "redaction",
        "normalization",
        "reconstruction",
        "failure_detection",
        "deduplication",
        "persistence",
        "clustering",
    ]
    assert all(e["status"] == "completed" for e in job["events"])


def test_upload_csv_and_log_files(client):
    csv_text = "timestamp,trace_id,prompt,completion\n2026-01-01T00:00:00Z,a,hello,hi\n2026-01-01T00:00:01Z,b,bye,\n"
    r = client.post("/api/v1/ingestion/upload", files={"file": ("x.csv", csv_text, "text/csv")})
    assert r.status_code == 201 and r.json()["trace_count"] == 2
    log = 'INFO trace_id=a user_input="hi" assistant_response="yo"\n'
    r = client.post("/api/v1/ingestion/upload", files={"file": ("x.log", log, "text/plain")})
    assert r.status_code == 201 and r.json()["file_format"] == "log"


def test_upload_rejects_bad_files(client):
    cases = [
        ("x.exe", b"MZ\x90\x00", "Unsupported"),
        ("x.jsonl", b"", "empty"),
        ("x.json", b'{"broken": ', "Malformed JSON"),
        ("x.csv", b"single\n1\n", "CSV"),
        ("x.jsonl", b"not json\nstill not", "No valid JSON"),
    ]
    for name, content, msg in cases:
        r = client.post(
            "/api/v1/ingestion/upload", files={"file": (name, io.BytesIO(content), "application/octet-stream")}
        )
        assert r.status_code == 422, (name, r.text)
        assert msg in r.json()["detail"]
    # rejected uploads that fail before parsing don't create jobs; parse failures leave a failed job
    jobs = client.get("/api/v1/ingestion/jobs").json()["items"]
    assert all(j["status"] == "failed" for j in jobs)


def test_upload_size_limit(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = client.post("/api/v1/ingestion/upload", files={"file": ("x.jsonl", b'{"input":"x"}', "application/json")})
    assert r.status_code == 413


def test_samples_list_and_unknown_sample(client):
    samples = client.get("/api/v1/ingestion/samples").json()
    assert all(s["available"] for s in samples)
    assert client.post("/api/v1/ingestion/sample?name=../../etc/passwd").status_code == 404


def test_all_samples_load(client):
    for name in ("production_logs", "openai_chat_logs", "support_bot_logs", "app_server"):
        r = client.post(f"/api/v1/ingestion/sample?name={name}")
        assert r.status_code == 201 and r.json()["status"] == "completed", name
    assert client.get("/api/v1/ingestion/jobs").json()["total"] == 4


def test_jobs_pagination_and_detail(client, loaded):
    page = client.get("/api/v1/ingestion/jobs?page=1&page_size=1").json()
    assert page["total"] == 1 and page["page_size"] == 1
    assert client.get(f"/api/v1/ingestion/jobs/{loaded['id']}").json()["id"] == loaded["id"]
    assert client.get("/api/v1/ingestion/jobs/nope").status_code == 404
    assert client.get("/api/v1/ingestion/jobs?page=0").status_code == 422


def test_traces_list_filters_and_detail(client, loaded):
    all_ = client.get("/api/v1/traces?page_size=200").json()
    assert all_["total"] == loaded["trace_count"]
    failed = client.get("/api/v1/traces?status=failed").json()
    assert failed["total"] > 0 and all(t["status"] == "failed" for t in failed["items"])
    dups = client.get("/api/v1/traces?duplicates=only").json()
    assert all(t["duplicate_of_id"] for t in dups["items"])
    timeouts = client.get("/api/v1/traces?failure_type=timeout").json()
    assert timeouts["total"] >= 4 and all("timeout" in t["failure_types"] for t in timeouts["items"])
    search = client.get("/api/v1/traces?search=migration").json()
    assert search["total"] >= 1
    conv = client.get("/api/v1/traces?search=IAM").json()["items"][0]
    detail = client.get(f"/api/v1/traces/{conv['id']}").json()
    assert detail["turn_count"] == 6 and len(detail["conversation"]) == 6
    assert client.get("/api/v1/traces/missing").status_code == 404


def test_failures_endpoints(client, loaded):
    s = client.get("/api/v1/failures/summary").json()
    assert s["total"] == s["observed"] + s["heuristic"] > 0
    types = {t["failure_type"] for t in s["by_type"]}
    assert {
        "timeout",
        "empty_response",
        "tool_call_failure",
        "hallucination_candidate",
        "malformed_structured_output",
    } <= types
    heur = client.get("/api/v1/failures?evidence=heuristic&page_size=200").json()
    assert all(f["evidence"] == "heuristic" for f in heur["items"])
    assert client.get("/api/v1/failures/types").json()["timeout"]


def test_clusters_endpoints(client, loaded):
    clusters = client.get("/api/v1/clusters").json()
    assert clusters["total"] >= 2
    c = clusters["items"][0]
    detail = client.get(f"/api/v1/clusters/{c['id']}").json()
    assert detail["representative"] is not None and detail["samples"]
    assert client.get("/api/v1/clusters/missing").status_code == 404


def test_generate_requires_data(client):
    r = client.post("/api/v1/datasets/generate", json={"name": "x"})
    assert r.status_code == 400 and "No processed traces" in r.json()["detail"]


def test_generate_validation(client, loaded):
    assert client.post("/api/v1/datasets/generate", json={"name": ""}).status_code == 422
    r = client.post("/api/v1/datasets/generate", json={"name": "x", "categories": ["nonexistent"]})
    assert r.status_code == 400


def test_dataset_generation_and_listing(client, dataset):
    stats = dataset["stats"]
    assert stats["total"] > 0 and stats["by_status"] == {"pending": stats["total"]}
    assert stats["category_coverage"] > 0.5
    assert dataset["versions"][0]["version_number"] == 1
    listing = client.get("/api/v1/datasets").json()
    assert listing["items"][0]["example_count"] == stats["total"]
    assert client.get("/api/v1/datasets/does-not-exist").status_code == 404


def test_generate_with_filters(client, loaded):
    r = client.post(
        "/api/v1/datasets/generate",
        json={"name": "failures", "include_successful": False, "categories": ["latency", "tool_usage"]},
    )
    assert r.status_code == 201
    cats = set(r.json()["stats"]["by_category"])
    assert cats <= {"latency", "tool_usage"} and cats


def test_examples_listing_filter_search_sort(client, dataset):
    ds = dataset["id"]
    page = client.get(f"/api/v1/datasets/{ds}/examples?page_size=5").json()
    assert len(page["items"]) == 5 and page["total"] == dataset["stats"]["total"]
    scores = [e["quality_score"] for e in page["items"]]
    assert scores == sorted(scores, reverse=True)
    lat = client.get(f"/api/v1/datasets/{ds}/examples?category=latency").json()
    assert lat["total"] > 0 and all(e["category"] == "latency" for e in lat["items"])
    found = client.get(f"/api/v1/datasets/{ds}/examples?search=password").json()
    assert found["total"] > 0
    assert client.get(f"/api/v1/datasets/{ds}/examples?status=bogus").status_code == 422
    assert client.get("/api/v1/datasets/missing/examples").status_code == 404


def test_categories_create(client):
    r = client.post("/api/v1/categories", json={"name": "pricing_accuracy", "description": "Prices"})
    assert r.status_code == 201 and not r.json()["is_builtin"]
    assert client.post("/api/v1/categories", json={"name": "pricing_accuracy"}).status_code == 409
    assert client.post("/api/v1/categories", json={"name": "Bad Name!"}).status_code == 422


def test_settings_read_and_protected_write(client, admin_enabled):
    s = client.get("/api/v1/settings").json()
    assert s["similarity_threshold"] == 0.90
    assert client.put("/api/v1/settings", json={"latency_threshold_ms": 5000}).status_code == 401
    r = client.put(
        "/api/v1/settings",
        json={"latency_threshold_ms": 5000, "custom_patterns": {"emp": r"EMP-\d+"}},
        headers={"X-Admin-Key": admin_enabled},
    )
    assert r.status_code == 200 and r.json()["latency_threshold_ms"] == 5000
    bad = client.put("/api/v1/settings", json={"custom_patterns": {"x": "("}}, headers={"X-Admin-Key": admin_enabled})
    assert bad.status_code == 422
    bad2 = client.put(
        "/api/v1/settings", json={"clustering_method": "spectral"}, headers={"X-Admin-Key": admin_enabled}
    )
    assert bad2.status_code == 422
    preview = client.post("/api/v1/privacy/preview", json={"text": "id EMP-42 mail a@b.co"}).json()
    assert "[REDACTED_EMP]" in preview["redacted"] and "[REDACTED_EMAIL]" in preview["redacted"]


def test_settings_change_affects_processing(client, admin_enabled):
    client.put("/api/v1/settings", json={"latency_threshold_ms": 100}, headers={"X-Admin-Key": admin_enabled})
    content = json.dumps({"trace_id": "a", "user_input": "question", "assistant_response": "ok", "latency_ms": 500})
    client.post("/api/v1/ingestion/upload", files={"file": ("a.jsonl", content, "application/json")})
    assert client.get("/api/v1/traces?failure_type=excessive_latency").json()["total"] == 1


def test_dashboard_metrics_reflect_data(client, dataset):
    m = client.get("/api/v1/dashboard/metrics").json()
    assert m["total_logs"] == 286
    assert m["total_traces"] > 0 and m["candidate_examples"] == dataset["stats"]["total"]
    assert m["approved_examples"] == 0
    assert 0 < m["duplicate_percentage"] < 100
    assert m["average_latency_ms"] > 0 and m["processing_success_rate"] == 100.0
    assert sum(b["count"] for b in m["latency_histogram"]) > 0
    assert m["failures_by_type"] and m["examples_by_category"]
