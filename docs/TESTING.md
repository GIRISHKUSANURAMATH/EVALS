# Testing

## How to run

```powershell
# Backend (from backend\ with the venv active)
pytest                                  # all 157 tests (1 POSIX-only test is skipped on Windows)
pytest --cov=app --cov-report=term      # with coverage
ruff check . ; ruff format --check .    # lint + formatting
mypy app                                # type checking

# Frontend (from frontend\)
npm ci
npm run lint        # ESLint
npm run typecheck   # tsc
npm test            # Vitest
npm run build       # production build

# End-to-end browser check (from the project root; backend + frontend running on an EMPTY database)
pip install playwright ; python -m playwright install chromium
python scripts\e2e_browser_check.py --url http://localhost:5173 --api http://127.0.0.1:8000
```

The E2E script never touches `docs/screenshots/` unless you pass `--screenshots`.
Downloaded exports are written to `docs/e2e_exports/` (git- and docker-ignored).

Backend tests use a fresh temporary SQLite database per test, created through the real
Alembic migrations (`tests/conftest.py`), so migrations are exercised on every run.

## Suites

| Suite | File | Tests | Covers |
| --- | --- | ---: | --- |
| Unit | `tests/unit/test_parsing.py` | 20 | JSONL/JSON/CSV/OpenAI/key=value parsing, field aliases, malformed lines, file validation |
| Unit | `tests/unit/test_redaction.py` | 30 | every PII/secret rule, Luhn and IP validation, false-positive guards, sensitive keys, custom patterns |
| Unit | `tests/unit/test_processing.py` | 22 | reconstruction, every failure detector and evidence level, dedup, K-means/DBSCAN clustering |
| Unit | `tests/unit/test_evaluation.py` | 16 | expected-output provenance, categories, quality factors, export validation |
| Unit | `tests/unit/test_migration_urls.py` | 5 | database URLs with `%`, spaces and Windows drive letters survive Alembic's ConfigParser; migrations run on such paths (the drive-letter test is POSIX-only) |
| API | `tests/api/test_api.py` | 24 | every endpoint, pagination, filters, status codes, persistence, migrations |
| API | `tests/api/test_review_export.py` | 7 | review workflow + history, bulk review, versions, exports in all formats and filters |
| Integration | `tests/integration/test_end_to_end.py` | 2 | upload → process → generate → review → approve → export → verify content; deterministic reprocessing |
| Security | `tests/security/test_security.py` | 25 | malicious uploads, path traversal, SQL injection in search, admin-key enforcement, no input echo, no content logging, no raw payload exposure, CORS, custom-pattern limits |
| Security | `tests/security/test_nesting_limits.py` | 6 | deeply nested JSON / JSONL is rejected or skipped with a clear message instead of crashing (HTTP 422 / per-record malformed) |
| Frontend | `frontend/src/test/app.test.tsx` | 12 | navigation, dashboard metrics, empty/error states, sample loading, upload (valid, rejected, server error), review approve/reject/flag, filtering/search, dataset generation, export URL + preview |
| Frontend | `frontend/src/test/review-sync.test.tsx` | 3 | the Human Review editor stays in sync with the filtered list (no stale editor after the last match is reviewed or a filter matches nothing); action confirmations name the reviewed example |
| Frontend | `frontend/src/test/api-errors.test.ts` | 7 | a stopped backend (bare 5xx from the dev proxy / nginx, or a network error) is reported as unreachable; real backend errors keep their message |
| E2E | `scripts/e2e_browser_check.py` | 1 workflow | see below |

### E2E workflow (`scripts/e2e_browser_check.py`)

Drives the real UI in Chromium against running servers:

1. Empty dashboard → load the synthetic sample → live metrics.
2. Upload `sample_data/support_bot_logs.csv` through the Upload page.
3. Processing Pipeline, Traces, Failure Analysis and Semantic Clusters pages render data.
4. Generate a dataset and open its detail page.
5. Human Review: approve (with an edited expected output), approve, reject, flag, then edit an
   approved example's expected output and note with **Save edits only**.
6. Verify the backend counts (2 approved / 1 rejected / 1 flagged) and the annotation history
   (`approve` then `edit`), with `expected_output_source = human_approved`.
7. Reload the browser and verify the statuses and the edit persisted.
8. Download approved-only exports in JSONL, CSV and JSON through the browser and inspect them:
   row count, review status, file extension, the edited expected output, no raw email addresses.
9. Full export contains every example with all four statuses; an empty export (no matching
   category) is valid; invalid requests return 422 / 400 / 404 / 400.
10. Settings page and a 390 px mobile layout render. Any browser console error fails the run.

## Latest recorded results

### Linux (development VM)

Run on **2026-11-06**: Linux x86_64 VM, 2 vCPU, 7.8 GB RAM, Python 3.11.18, Node 22.23, npm 10.9.

| Check | Result |
| --- | --- |
| Backend tests | **157 passed**, 0 failed, 0 skipped |
| Backend line coverage | **96.7%** (2,667 statements, 87 missed) |
| ruff check / ruff format --check | clean |
| mypy (43 source files) | no issues |
| `npm ci` / lint / typecheck | clean |
| Frontend tests (Vitest) | **22 passed** (3 files) |
| Production build (`vite build`) | succeeded |
| E2E browser check (Playwright, Chromium) | **passed**, 0 browser console errors, 0 backend errors |

Lowest-covered modules: `processing/embeddings.py` (62% — the sentence-transformers path
only runs when that optional package is installed) and `core/logging.py` (69%).

### Windows

The first Windows run (Python 3.11.9) failed at startup with
`ValueError: invalid interpolation syntax`: SQLAlchemy percent-encodes the drive letter
(`C:` → `C%3A`) and Alembic's ConfigParser treats `%` as interpolation.
Fixed in `app/database/session.py` and covered by `tests/unit/test_migration_urls.py`. After the fix (2026-11-06, Python 3.11.9): **156 passed, 1 skipped** (the POSIX-only drive-letter test); frontend 22 passed; lint, typecheck and production build clean; Human Review verified manually in the running app.

### Not verified

Docker image builds (Docker Hub unreachable from the verification VM), PostgreSQL, frontend
line coverage (no coverage provider installed), and the first GitHub Actions run.
