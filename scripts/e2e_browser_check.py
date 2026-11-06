"""End-to-end browser check of a RUNNING EVALS instance (backend + frontend).

Drives the real UI with Playwright: loads the synthetic sample, uploads a CSV file,
generates a dataset, approves / rejects / flags examples, edits an expected output, checks
the annotation history, reloads the browser to confirm persistence, exports in all three
formats and validates the downloaded files. Fails on any browser console error.

Prerequisites: backend on :8000 and frontend on :5173 started against an EMPTY database.
    pip install playwright && python -m playwright install chromium
    python scripts/e2e_browser_check.py --url http://127.0.0.1:5173 --api http://127.0.0.1:8000
Add --screenshots to (over)write docs/screenshots/*.png.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TAKE_SCREENSHOTS = False
API = "http://127.0.0.1:8000"


def api_get(path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(API + path, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def api_json(path: str) -> dict:
    code, body = api_get(path)
    assert code == 200, f"GET {path} -> {code}: {body[:200]!r}"
    return json.loads(body)


def shot(page: Page, name: str) -> None:
    if not TAKE_SCREENSHOTS:
        return
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)  # let charts finish their entry animation
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def step(msg: str) -> None:
    print(f"  ✓ {msg}", flush=True)


def run(url: str, headed: bool) -> int:
    console_errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        # 1. Empty dashboard
        page.goto(url)
        expect(page.get_by_role("button", name="Load synthetic sample data")).to_be_visible()
        shot(page, "01-empty-dashboard")
        step("empty dashboard renders with sample-data option")

        # 2. Load sample data from the dashboard
        page.get_by_role("button", name="Load synthetic sample data").click()
        expect(page.get_by_text("Logs ingested", exact=True)).to_be_visible(timeout=60_000)
        shot(page, "04-dashboard")
        step("sample data processed; dashboard shows live metrics")

        # 3. Upload a real file (CSV) through the Upload page
        page.goto(f"{url}/upload")
        page.locator("input[type=file]").set_input_files(str(ROOT / "sample_data" / "support_bot_logs.csv"))
        page.get_by_role("button", name="Upload & process").click()
        expect(page.get_by_text("Processed support_bot_logs.csv")).to_be_visible(timeout=60_000)
        shot(page, "02-upload")
        step("CSV upload processed through the UI")

        # 4. Pipeline, traces, failures, clusters pages render data
        for path, name, text in [
            ("pipeline", "03-pipeline", "Processing Pipeline"),
            ("traces", "05-traces", "Traces"),
            ("failures", "06-failures", "Failure Analysis"),
            ("clusters", "07-clusters", "Semantic Clusters"),
        ]:
            page.goto(f"{url}/{path}")
            expect(page.get_by_role("heading", name=text).first).to_be_visible()
            page.wait_for_load_state("networkidle")
            shot(page, name)
        step("pipeline / traces / failures / clusters pages render")

        # 5. Generate a dataset
        page.goto(f"{url}/datasets")
        page.get_by_role("button", name="Generate dataset").click()
        page.wait_for_url(re.compile(r".*/datasets/[0-9a-f-]{36}$"), timeout=60_000)
        page.wait_for_load_state("networkidle")
        shot(page, "08-dataset-detail")
        dataset_id = page.url.rsplit("/", 1)[-1]
        step(f"dataset generated ({dataset_id[:8]})")

        # 6. Review: approve two examples (one with an edited expected output), reject one
        page.goto(f"{url}/review?dataset={dataset_id}")
        items = page.get_by_test_id("example-list").get_by_role("button")
        expect(items.first).to_be_visible()
        items.first.click()
        page.get_by_label("Expected output").fill("Reviewer-approved reference answer.")
        page.get_by_role("button", name="Approve").click()
        expect(page.get_by_text("Approved", exact=True).first).to_be_visible()
        for action in ("Approve", "Reject"):
            page.get_by_role("tab", name="pending").click()
            page.get_by_test_id("example-list").get_by_role("button").first.click()
            page.get_by_role("button", name=action).click()
            expect(page.get_by_text({"Approve": "Approved", "Reject": "Rejected"}[action], exact=True).first).to_be_visible()
        page.get_by_role("tab", name="approved").click()
        expect(page.get_by_test_id("example-list").get_by_role("button")).to_have_count(2)
        step("approved 2 examples (1 with edited expected output) and rejected 1")

        # 6b. Flag an uncertain example; the confirmation must name the example
        page.get_by_role("tab", name="pending").click()
        page.get_by_test_id("example-list").get_by_role("button").first.click()
        page.get_by_role("button", name="Flag uncertain").click()
        expect(page.get_by_test_id("review-notice")).to_contain_text("Flagged as uncertain tr_")
        flagged_key = page.get_by_test_id("review-notice").inner_text().rsplit(" ", 1)[-1]
        step(f"flagged {flagged_key} as uncertain")

        # 6c. Edit an expected output + note on an approved example and save the edit only
        edited_text = "Edited reference answer saved by the E2E check."
        page.get_by_role("tab", name="approved").click()
        page.get_by_test_id("example-list").get_by_role("button").first.click()
        page.get_by_label("Expected output").fill(edited_text)
        page.get_by_label("Reviewer notes").fill("e2e edit note")
        page.get_by_role("button", name="Save edits only").click()
        expect(page.get_by_test_id("review-notice")).to_contain_text("Edits saved for tr_")
        edited_key = page.get_by_test_id("review-notice").inner_text().rsplit(" ", 1)[-1]
        step(f"saved an edited expected output on {edited_key}")

        # 6d. Backend state + annotation history must match what the UI did
        examples = api_json(f"/api/v1/datasets/{dataset_id}/examples?page_size=200")["items"]
        by_status: dict[str, int] = {}
        for e in examples:
            by_status[e["review_status"]] = by_status.get(e["review_status"], 0) + 1
        assert by_status.get("approved") == 2 and by_status.get("rejected") == 1 and by_status.get("flagged") == 1, by_status
        edited = next(e for e in examples if e["source_trace_key"] == edited_key)
        detail = api_json(f"/api/v1/examples/{edited['id']}")
        actions = [a["action"] for a in detail["annotations"]]
        assert actions[:1] == ["approve"] and actions[-1] == "edit", actions
        assert detail["expected_output"] == edited_text and detail["expected_output_source"] == "human_approved", detail
        assert detail["reviewer_notes"] == "e2e edit note", detail["reviewer_notes"]
        expect(page.get_by_text("by reviewer").first).to_be_visible()  # history panel renders entries
        step(f"backend counts {by_status}; history for {edited_key} = {actions}")

        # 6e. Reload the browser: review state must persist
        page.reload()
        page.wait_for_load_state("networkidle")
        for tab, count in (("approved", 2), ("rejected", 1), ("flagged", 1)):
            page.get_by_role("tab", name=tab).click()
            expect(page.get_by_test_id("example-list").get_by_role("button")).to_have_count(count)
        page.get_by_role("tab", name="approved").click()
        page.get_by_test_id("example-list").get_by_role("button").filter(has_text=edited["input"][:40]).first.click()
        expect(page.get_by_label("Expected output")).to_have_value(edited_text)
        shot(page, "09-review")
        step("after browser reload: 2 approved / 1 rejected / 1 flagged and the edit persisted")

        # 7. Export approved-only in every format and validate the files
        page.goto(f"{url}/export")
        out_dir = ROOT / "docs" / "e2e_exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        for fmt in ("jsonl", "csv", "json"):
            page.get_by_role("radio", name=f".{fmt}", exact=True).click()
            with page.expect_download() as dl:
                page.get_by_test_id("download-link").click()
            path = out_dir / f"approved.{fmt}"
            dl.value.save_as(path)
            text = path.read_text(encoding="utf-8")
            if fmt == "jsonl":
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            elif fmt == "csv":
                rows = list(csv.DictReader(io.StringIO(text)))
            else:
                rows = json.loads(text)["examples"]
            assert len(rows) == 2, f"{fmt}: expected 2 approved rows, got {len(rows)}"
            assert all(r["review_status"] == "approved" for r in rows), f"{fmt}: non-approved row exported"
            sources = {r["expected_output_source"] for r in rows}
            assert "human_approved" in sources, f"{fmt}: edited expected output not marked human_approved"
            assert not EMAIL.search(text), f"{fmt}: an unredacted email address leaked into the export"
            assert path.suffix == f".{fmt}" and dl.value.suggested_filename.endswith(f".{fmt}"), dl.value.suggested_filename
            exported = next(r for r in rows if r["source_trace_id"] == edited_key)
            assert exported["expected_output"] == edited_text, exported["expected_output"]
            step(f"{fmt} export: 2 approved rows, edited expected output present, no raw emails")
        # 7b. Full export, empty export, invalid requests (API level)
        code, body = api_get(f"/api/v1/exports/{dataset_id}?format=jsonl")
        rows = [json.loads(line) for line in body.decode().splitlines() if line.strip()]
        assert code == 200 and len(rows) == len(examples), (code, len(rows), len(examples))
        statuses = {r["review_status"] for r in rows}
        assert statuses == {"pending", "approved", "rejected", "flagged"}, statuses
        code, body = api_get(f"/api/v1/exports/{dataset_id}?format=json&approved_only=true&categories=no_such_category")
        assert code == 200 and json.loads(body)["examples"] == [], (code, body[:200])
        for bad, want in ((f"/api/v1/exports/{dataset_id}?format=xml", 422), ("/api/v1/exports/not-a-uuid", 400),
                          ("/api/v1/exports/00000000-0000-0000-0000-000000000000", 404),
                          (f"/api/v1/exports/{dataset_id}?statuses=bogus", 400)):
            code, _ = api_get(bad)
            assert code == want, f"{bad}: expected {want}, got {code}"
        step(f"full export {len(rows)} rows with all 4 statuses; empty export valid; invalid requests -> 422/400/404/400")
        page.get_by_role("radio", name=".jsonl", exact=True).click()
        page.get_by_role("button", name="Preview").click()
        expect(page.get_by_test_id("export-preview")).to_be_visible()
        shot(page, "10-export")

        page.goto(f"{url}/settings")
        expect(page.get_by_role("heading", name="Settings").first).to_be_visible()
        shot(page, "11-settings")

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(url)
        expect(page.get_by_text("Logs ingested", exact=True)).to_be_visible()
        shot(page, "12-mobile-dashboard")
        step("settings and mobile layout render")

        browser.close()

    if console_errors:
        print("\nBrowser console errors:")
        for e in console_errors:
            print("  -", e)
        return 1
    print("\nE2E browser check PASSED with 0 console errors.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:5173")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--screenshots", action="store_true", help="overwrite docs/screenshots/*.png")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    TAKE_SCREENSHOTS = args.screenshots
    API = args.api.rstrip("/")
    sys.exit(run(args.url.rstrip("/"), args.headed))
