"""Full workflow: upload -> process -> generate -> review -> approve -> export -> verify."""

import json

from tests.conftest import SAMPLE_DIR

SECRETS_IN_SAMPLE = [
    "priya.sharma@example.com",
    "john.miller@example.org",
    "+91 98765 43210",
    "(415) 555-0134",
    "sk-test-FAKE0000000000000000abcd",
    "AKIAFAKEEXAMPLE00000",
    "ghp_FAKEexampleTOKEN000000000000000000",
    "4111 1111 1111 1111",
    "hunter2",
    "203.0.113.42",
]


def test_full_workflow(client, db):
    raw = (SAMPLE_DIR / "production_logs.jsonl").read_bytes()
    for s in SECRETS_IN_SAMPLE:
        assert s.encode() in raw, f"sample should contain {s} so the test is meaningful"

    # 1. Upload real file through the API
    up = client.post("/api/v1/ingestion/upload", files={"file": ("production_logs.jsonl", raw, "application/json")})
    assert up.status_code == 201
    job = up.json()
    assert job["status"] == "completed"
    assert job["invalid_records"] == 4  # 3 malformed lines + 1 record without content

    # 2. Processing results
    metrics = client.get("/api/v1/dashboard/metrics").json()
    assert metrics["total_traces"] == job["trace_count"]
    assert metrics["detected_failures"] > 0 and metrics["clusters"] > 0

    # 3. Generate
    ds = client.post("/api/v1/datasets/generate", json={"name": "e2e"}).json()
    ds_id = ds["id"]
    examples = client.get(f"/api/v1/datasets/{ds_id}/examples?page_size=200").json()["items"]
    assert len(examples) == ds["stats"]["total"] > 20
    # No generated example claims a human-approved reference before review.
    assert all(e["expected_output_source"] != "human_approved" for e in examples)
    assert all(e["failure_evidence"] in ("observed", "heuristic", "none") for e in examples)

    # 4. Review: approve failures with an edited expected output, reject one
    failures = [e for e in examples if e["failure_type"]][:3]
    for e in failures:
        r = client.post(
            f"/api/v1/examples/{e['id']}/review",
            json={"action": "approve", "reviewer": "qa", "expected_output": "Graceful, correct answer."},
        )
        assert r.status_code == 200
    rejected = next(e for e in examples if e not in failures)
    client.post(f"/api/v1/examples/{rejected['id']}/review", json={"action": "reject", "reviewer": "qa"})

    # 5. Export approved
    out = client.get(f"/api/v1/exports/{ds_id}?format=jsonl&approved_only=true")
    records = [json.loads(line) for line in out.text.splitlines()]
    assert {r["id"] for r in records} == {e["id"] for e in failures}
    assert all(r["expected_output_source"] == "human_approved" for r in records)
    assert all(r["expected_output"] == "Graceful, correct answer." for r in records)

    # 6. No raw secret appears anywhere: exports, API responses, or the database
    full_export = client.get(f"/api/v1/exports/{ds_id}?format=json").text
    traces_dump = json.dumps(
        [
            client.get(f"/api/v1/traces/{t['id']}").json()
            for t in client.get("/api/v1/traces?page_size=200").json()["items"]
        ]
    )
    for s in SECRETS_IN_SAMPLE:
        assert s not in full_export, s
        assert s not in traces_dump, s
    from sqlalchemy import text

    for table in ("log_records", "traces", "eval_examples", "failures"):
        rows = db.execute(text(f"SELECT * FROM {table}")).fetchall()
        blob = json.dumps([list(map(str, r)) for r in rows])
        for s in SECRETS_IN_SAMPLE:
            assert s not in blob, (table, s)


def test_reprocessing_is_deterministic(client):
    a = client.post("/api/v1/ingestion/sample?name=production_logs").json()
    b = client.post("/api/v1/ingestion/sample?name=production_logs").json()
    assert a["trace_count"] == b["trace_count"]
    assert a["stats"]["duplicates"] == b["stats"]["duplicates"]
    assert a["redaction_counts"] == b["redaction_counts"]
