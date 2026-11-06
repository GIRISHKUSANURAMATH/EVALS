# API reference

Base URL: `http://127.0.0.1:8000`. All endpoints are under `/api/v1` except `/health`.
Interactive OpenAPI docs: `/docs` (Swagger UI) and `/redoc`; schema at `/openapi.json`.

Conventions

- List endpoints are paginated: `?page=1&page_size=25` → `{"items": [...], "total", "page", "page_size"}`.
- Errors: `{"detail": "message"}` (422 validation errors return a list without echoing input values).
- Status codes: 200 OK · 201 created · 204 no content · 400 bad parameter · 401 bad admin key ·
  403 admin operations disabled · 404 not found · 409 conflict · 413 file too large ·
  415 unsupported file type · 422 validation error · 500 unexpected error.
- Admin-protected endpoints need header `X-Admin-Key: <EVALS_ADMIN_API_KEY>`.

## Ingestion

| Method | Path | Description |
| --- | --- | --- |
| POST | `/ingestion/upload` | multipart `file`; runs the full pipeline; returns the job with per-stage events (201) |
| POST | `/ingestion/sample?name=production_logs` | process a bundled synthetic file: `production_logs`, `openai_chat_logs`, `support_bot_logs`, `app_server` |
| GET | `/ingestion/samples` | list bundled sample files |
| GET | `/ingestion/jobs?status=` | paginated jobs |
| GET | `/ingestion/jobs/{job_id}` | job detail with processing events |

```powershell
curl.exe -F "file=@sample_data/support_bot_logs.csv" http://127.0.0.1:8000/api/v1/ingestion/upload
```

## Traces, failures, clusters

| Method | Path | Filters |
| --- | --- | --- |
| GET | `/traces` | `status`, `job_id`, `failure_type`, `cluster_id`, `duplicates=only\|exclude`, `search`, pagination |
| GET | `/traces/{trace_id}` | full conversation, failures, duplicate info |
| GET | `/failures` | `failure_type`, `evidence=observed\|heuristic`, `severity`, pagination |
| GET | `/failures/summary` | counts by type / evidence / severity |
| GET | `/failures/types` | failure type catalogue with descriptions |
| GET | `/clusters` | pagination |
| GET | `/clusters/{cluster_id}?samples=10` | cluster with sample traces |

## Datasets and examples

| Method | Path | Description |
| --- | --- | --- |
| GET | `/datasets` | paginated datasets with status counts |
| POST | `/datasets/generate` | body below; 201 |
| GET | `/datasets/{id}` | detail with stats and versions |
| DELETE | `/datasets/{id}` | **admin**; 204 |
| POST | `/datasets/{id}/versions` | `{"notes": "..."}` freeze a snapshot; 201 |
| GET | `/datasets/{id}/examples` | `status`, `category`, `failure_type`, `search`, `sort=quality_desc\|quality_asc\|newest\|oldest` |
| GET | `/examples/{id}` | example with quality factors and annotation history |
| PATCH | `/examples/{id}` | edit `expected_output`, `category`, `reviewer_notes` |
| POST | `/examples/{id}/review` | `{"action": "approve\|reject\|flag\|reset", "reviewer", "note", "expected_output?", "category?"}` |
| POST | `/examples/bulk-review` | `{"example_ids": [...], "action": ...}` (max 500) |

Generate request:

```json
{
  "name": "support-bot-regressions",
  "description": "Nov traffic",
  "job_ids": null,
  "include_successful": true,
  "exclude_duplicates": true,
  "categories": ["tool_usage", "formatting"],
  "min_quality": 0.5,
  "max_examples": 5000
}
```

Approving with an `expected_output` sets `expected_output_source = "human_approved"`.

## Export

`GET /exports/{dataset_id}?format=jsonl|csv|json&approved_only=true&categories=a,b&statuses=approved&date_from=2026-01-01T00:00:00&date_to=...`

Returns the file as an attachment with headers `Content-Disposition` and `X-Example-Count`.
Every record is validated against the export schema before rendering. JSON exports wrap
records as `{"manifest": {...filters, counts, generated_at}, "examples": [...]}`.

| Field | Meaning |
| --- | --- |
| `input`, `messages`, `system_prompt` | the evaluated request and its prior conversation |
| `actual_output` | what production returned (observed) |
| `expected_output` | reference answer, or `null` |
| `expected_output_source` | `none` \| `candidate` \| `human_approved` |
| `category`, `failure_type`, `failure_evidence` | labels and their evidence level |
| `review_status` | `pending` \| `approved` \| `rejected` \| `flagged` |
| `confidence_score`, `quality_score` | 0–1 |
| `source_trace_id`, `source_timestamp`, `metadata` | provenance |

## System

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | status, version, database, embeddings availability, whether admin ops are enabled |
| GET | `/dashboard/metrics` | all dashboard figures, computed from the database |
| GET / POST | `/categories` | list / create custom category (`^[a-z][a-z0-9_]{1,63}$`) |
| GET | `/settings` | runtime pipeline settings |
| PUT | `/settings` | **admin**; partial update |
| POST | `/privacy/preview` | `{"text": "..."}` → redacted text and counts (nothing stored) |
| POST | `/admin/reset` | **admin**; delete all data; 204 |
