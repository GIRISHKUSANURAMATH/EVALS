import io
import json
import logging

import pytest

from app.core.security import sanitize_filename


@pytest.mark.parametrize(
    "name,expected",
    [
        ("../../etc/passwd.jsonl", "passwd.jsonl"),
        ("..\\..\\windows\\system32\\evil.csv", "evil.csv"),
        ("C:\\Users\\x\\logs.jsonl", "logs.jsonl"),
        ("<script>alert(1)</script>.json", "script_.json"),
        ("", "upload"),
        (None, "upload"),
        ("....", "upload"),
    ],
)
def test_sanitize_filename(name, expected):
    out = sanitize_filename(name)
    assert "/" not in out and "\\" not in out and ".." not in out
    assert out == expected


def test_path_traversal_filename_upload_is_sanitized(client):
    r = client.post(
        "/api/v1/ingestion/upload",
        files={"file": ("../../../../etc/cron.d/x.jsonl", b'{"input": "x", "output": "y"}', "application/json")},
    )
    assert r.status_code == 201
    assert r.json()["filename"] == "x.jsonl"


def test_path_traversal_in_export_and_sample(client):
    assert client.get("/api/v1/exports/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
    assert client.post("/api/v1/ingestion/sample?name=..%2F..%2F.env").status_code == 404


@pytest.mark.parametrize(
    "name,content",
    [
        ("payload.jsonl", b"MZ\x90\x00\x03\x00\x00\x00"),  # Windows executable disguised
        ("payload.csv", b"PK\x03\x04\x14\x00"),  # zip archive
        ("payload.json", b"\x7fELF\x02\x01\x01"),
        ("payload.log", b"%PDF-1.7\n"),
        ("payload.jsonl", b"\x1f\x8b\x08\x00"),  # gzip
        ("payload.php", b"<?php system($_GET['c']); ?>"),
        ("payload.jsonl.exe", b"{}"),
    ],
)
def test_malicious_uploads_rejected(client, name, content):
    r = client.post("/api/v1/ingestion/upload", files={"file": (name, io.BytesIO(content), "application/octet-stream")})
    assert r.status_code == 422


def test_deeply_nested_and_huge_field_json_handled(client):
    nested = {"input": "x", "metadata": {}}
    cur = nested["metadata"]
    for _ in range(50):
        cur["a"] = {}
        cur = cur["a"]
    big = {"input": "y" * 200_000, "output": "z"}
    content = json.dumps(nested) + "\n" + json.dumps(big)
    r = client.post("/api/v1/ingestion/upload", files={"file": ("n.jsonl", content, "application/json")})
    assert r.status_code == 201


def test_sql_injection_in_search_is_harmless(client, loaded):
    r = client.get("/api/v1/traces", params={"search": "' OR 1=1; DROP TABLE traces; --"})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/api/v1/traces").json()["total"] > 0


def test_destructive_ops_disabled_without_admin_key(client, dataset):
    assert client.delete(f"/api/v1/datasets/{dataset['id']}").status_code == 403
    assert client.post("/api/v1/admin/reset").status_code == 403
    assert client.put("/api/v1/settings", json={"latency_threshold_ms": 500}).status_code == 403


def test_destructive_ops_require_valid_key(client, dataset, admin_enabled):
    ds = dataset["id"]
    assert client.delete(f"/api/v1/datasets/{ds}").status_code == 401
    assert client.delete(f"/api/v1/datasets/{ds}", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.delete(f"/api/v1/datasets/{ds}", headers={"X-Admin-Key": admin_enabled}).status_code == 204
    assert client.get(f"/api/v1/datasets/{ds}").status_code == 404
    assert client.post("/api/v1/admin/reset", headers={"X-Admin-Key": admin_enabled}).status_code == 204
    m = client.get("/api/v1/dashboard/metrics").json()
    assert m["total_logs"] == 0 and m["total_traces"] == 0
    assert client.get("/api/v1/categories").json()  # builtins restored


def test_validation_errors_do_not_echo_input(client):
    secret = "sk-shouldnotbeechoed1234567890"
    r = client.post("/api/v1/datasets/generate", json={"name": secret, "max_examples": -1})
    assert r.status_code == 422
    assert secret not in r.text


def test_uploaded_content_is_not_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    marker = "very-private-content@example.com"
    client.post(
        "/api/v1/ingestion/upload",
        files={"file": ("p.jsonl", json.dumps({"input": marker, "output": "ok"}), "application/json")},
    )
    assert marker not in caplog.text
    assert "very-private-content" not in caplog.text


def test_raw_api_never_exposes_raw_payload(client, loaded):
    t = client.get("/api/v1/traces?page_size=1").json()["items"][0]
    detail = client.get(f"/api/v1/traces/{t['id']}").text
    assert "raw_payload" not in detail


def test_cors_restricted_to_configured_origins(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_redos_resistant_custom_pattern_length_limit(client, admin_enabled):
    r = client.put(
        "/api/v1/settings", json={"custom_patterns": {"x": "a" * 600}}, headers={"X-Admin-Key": admin_enabled}
    )
    assert r.status_code == 422
