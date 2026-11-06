import csv
import io
import json


def _examples(client, ds, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/v1/datasets/{ds}/examples?page_size=200&{q}").json()["items"]


def test_review_approve_reject_flag_and_history(client, dataset):
    ds = dataset["id"]
    items = _examples(client, ds)
    a, b, c = items[0]["id"], items[1]["id"], items[2]["id"]

    r = client.post(
        f"/api/v1/examples/{a}/review",
        json={"action": "approve", "reviewer": "girish", "expected_output": "Correct answer", "note": "looks right"},
    )
    assert r.status_code == 200
    ex = r.json()
    assert ex["review_status"] == "approved"
    assert ex["expected_output"] == "Correct answer" and ex["expected_output_source"] == "human_approved"
    assert ex["reviewer_notes"] == "looks right"
    review_factor = next(f for f in ex["quality_factors"] if f["name"] == "review_status")
    assert review_factor["value"] == 1.0

    assert client.post(f"/api/v1/examples/{b}/review", json={"action": "reject"}).json()["review_status"] == "rejected"
    flagged = client.post(f"/api/v1/examples/{c}/review", json={"action": "flag", "note": "unsure"}).json()
    assert flagged["review_status"] == "flagged"

    # Reverting an approval demotes the human-approved reference back to a candidate.
    reset = client.post(f"/api/v1/examples/{a}/review", json={"action": "reset"}).json()
    assert reset["review_status"] == "pending" and reset["expected_output_source"] == "candidate"

    detail = client.get(f"/api/v1/examples/{a}").json()
    actions = [h["action"] for h in detail["annotations"]]
    assert actions == ["approve", "reset"]
    assert detail["annotations"][0]["reviewer"] == "girish"
    assert detail["annotations"][0]["previous_values"]["review_status"] == "pending"


def test_patch_example_edit_category_notes(client, dataset):
    ex = _examples(client, dataset["id"])[0]
    r = client.patch(
        f"/api/v1/examples/{ex['id']}",
        json={"expected_output": "Better", "category": "safety", "reviewer_notes": "n", "reviewer": "rev"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["expected_output"] == "Better" and body["expected_output_source"] == "candidate"
    assert body["category"] == "safety" and body["confidence_score"] == 1.0
    assert client.patch(f"/api/v1/examples/{ex['id']}", json={"category": "nope"}).status_code == 400
    assert client.patch("/api/v1/examples/missing", json={"reviewer_notes": "x"}).status_code == 404
    hist = client.get(f"/api/v1/examples/{ex['id']}").json()["annotations"]
    assert hist[0]["action"] == "edit" and hist[0]["new_values"]["category"] == "safety"


def test_review_validation(client, dataset):
    ex = _examples(client, dataset["id"])[0]
    assert client.post(f"/api/v1/examples/{ex['id']}/review", json={"action": "delete"}).status_code == 422
    assert client.post("/api/v1/examples/missing/review", json={"action": "approve"}).status_code == 404
    r = client.post(f"/api/v1/examples/{ex['id']}/review", json={"action": "approve", "category": "unknown_cat"})
    assert r.status_code == 400


def test_bulk_review_and_status_filter(client, dataset):
    ds = dataset["id"]
    ids = [e["id"] for e in _examples(client, ds)[:5]]
    r = client.post("/api/v1/examples/bulk-review", json={"example_ids": ids + ["missing"], "action": "approve"})
    assert r.json() == {"updated": 5, "not_found": ["missing"]}
    approved = _examples(client, ds, status="approved")
    assert {e["id"] for e in approved} == set(ids)


def test_versions(client, dataset):
    ds = dataset["id"]
    ex = _examples(client, ds)[0]
    client.post(f"/api/v1/examples/{ex['id']}/review", json={"action": "approve"})
    v = client.post(f"/api/v1/datasets/{ds}/versions", json={"notes": "after review"})
    assert v.status_code == 201 and v.json()["version_number"] == 2 and v.json()["approved_count"] == 1
    detail = client.get(f"/api/v1/datasets/{ds}").json()
    assert detail["current_version"] == 2
    assert detail["versions"][0]["checksum"] != detail["versions"][1]["checksum"]


def test_exports_all_formats_and_filters(client, dataset):
    ds = dataset["id"]
    items = _examples(client, ds)
    approve_ids = [items[0]["id"], items[1]["id"]]
    for eid in approve_ids:
        client.post(f"/api/v1/examples/{eid}/review", json={"action": "approve"})

    r = client.get(f"/api/v1/exports/{ds}?format=jsonl&approved_only=true")
    assert r.status_code == 200 and r.headers["x-example-count"] == "2"
    assert "attachment" in r.headers["content-disposition"]
    lines = [json.loads(x) for x in r.text.strip().splitlines()]
    assert {x["id"] for x in lines} == set(approve_ids)
    assert all(x["review_status"] == "approved" and x["messages"][-1]["role"] == "user" for x in lines)

    j = client.get(f"/api/v1/exports/{ds}?format=json").json()
    assert j["manifest"]["example_count"] == len(items) and len(j["examples"]) == len(items)

    c = client.get(f"/api/v1/exports/{ds}?format=csv&categories=latency")
    rows = list(csv.DictReader(io.StringIO(c.text)))
    assert rows and all(row["category"] == "latency" for row in rows)

    future = client.get(f"/api/v1/exports/{ds}?format=jsonl&date_from=2099-01-01T00:00:00")
    assert future.text == "" and future.headers["x-example-count"] == "0"
    window = client.get(f"/api/v1/exports/{ds}?format=json&date_from=2026-09-01T00:00:00&date_to=2026-09-30T00:00:00")
    assert window.json()["manifest"]["example_count"] > 0

    st = client.get(f"/api/v1/exports/{ds}?format=json&statuses=pending").json()
    assert all(e["review_status"] == "pending" for e in st["examples"])


def test_export_input_validation(client, dataset):
    ds = dataset["id"]
    assert client.get(f"/api/v1/exports/{ds}?format=xml").status_code == 422
    assert client.get(f"/api/v1/exports/{ds}?statuses=evil").status_code == 400
    assert client.get("/api/v1/exports/not-a-uuid").status_code == 400
    assert client.get("/api/v1/exports/00000000-0000-0000-0000-000000000000").status_code == 404
