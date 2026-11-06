# Architecture

## Layers

```
React SPA (frontend/src)
   │  fetch /api/v1/*   (Vite dev proxy, or nginx in Docker)
   ▼
FastAPI routers (app/api/routes)      HTTP concerns only: validation, status codes, pagination
   │
   ▼
Services (app/services)               orchestration + transactions
   │   pipeline.py      upload → stages → persistence, ProcessingEvent per stage
   │   datasets.py      generation, versions, review, export, re-scoring
   │   settings_service runtime settings stored in the DB
   ▼
Pure pipeline modules                 no DB, no HTTP: plain dataclasses in / out
   ingestion/   validation.py · parsers.py · normalizer.py · schema.py
   privacy/     redactor.py · pipeline.py
   processing/  reconstruction.py · failures.py · dedup.py · clustering.py · embeddings.py · text.py
   evaluation/  categories.py · generator.py · scoring.py · exporters.py · llm.py
   ▼
SQLAlchemy models (app/models/entities.py) ── Alembic migrations ── SQLite / PostgreSQL
```

The pure modules are why each pipeline stage is unit-testable in isolation
(`tests/unit/*`): e.g. `deduplicate(items, cfg)` takes `DedupItem`s and returns results
without touching the database.

## Request flow: upload

1. `POST /api/v1/ingestion/upload` reads the file (size-checked), sanitises the filename.
2. `services.pipeline.process_upload` creates an `IngestionJob`, then runs stages inside a
   `_StageRecorder` that writes a `ProcessingEvent` (stage, status, duration, counts) for
   each: validation → parsing → redaction → normalization → reconstruction →
   failure_detection → deduplication → persistence → clustering.
3. A failing stage marks the job `failed` with a user-safe message; nothing partial is kept.
4. The response is the job with its events, which the Processing Pipeline page renders.

## Request flow: dataset → review → export

1. `POST /api/v1/datasets/generate` snapshots processed traces into `TraceSnapshot`s,
   calls `evaluation.generator.generate_examples`, persists `EvalExample`s and version 1.
2. `POST /api/v1/examples/{id}/review` and `PATCH /api/v1/examples/{id}` change review
   state / fields, write a `ReviewAnnotation` (before/after diff) and re-score the example.
3. `POST /api/v1/datasets/{id}/versions` freezes the current examples into a new version.
4. `GET /api/v1/exports/{id}` filters, converts to `ExportRecord`s, validates every record
   with Pydantic, renders JSONL / CSV / JSON (JSON includes a manifest).

## Data model (12 tables)

| Table | Purpose | Key relations / indexes |
| --- | --- | --- |
| `ingestion_jobs` | one per upload: format, size, counts, redaction counts, stats, status | index on status, created_at |
| `log_records` | normalised (redacted) records | FK job; index on job, trace key |
| `traces` | reconstructed conversations, status, dedup + cluster assignment | FK job, cluster; unique (job_id, trace_key); index (job_id, status) |
| `failures` | one row per detected signal with `evidence` and severity | FK trace; index on type |
| `clusters` | label, size, top terms, failure rate, representative trace (per upload) | FK job |
| `datasets` | name, description | — |
| `dataset_versions` | immutable JSON snapshot of examples | FK dataset; unique (dataset, version) |
| `eval_examples` | input, outputs, provenance, category, scores, review state | FK dataset, trace; indexes (dataset, status), (dataset, category) |
| `review_annotations` | append-only history of review actions with diffs | FK example |
| `processing_events` | per-stage timing and details | FK job |
| `categories` | built-in + custom evaluation categories | unique name |
| `app_settings` | runtime settings edited from the UI | — |

All primary keys are UUID strings so the schema ports to PostgreSQL unchanged. JSON
columns use SQLAlchemy's generic `JSON` type. Cascading deletes are declared on the
relationships; SQLite foreign-key enforcement is switched on with a `PRAGMA` at connect time.

## Configuration

Two levels:

- **Environment** (`app/core/config.py`, `EVALS_*` variables or `.env`): database URL, CORS,
  upload limits, admin key, raw-content preservation, embedding/LLM switches.
- **Runtime** (`app_settings` table, Settings page): latency threshold, similarity
  threshold, clustering method, max clusters, sensitive field names, custom regexes,
  repeated-failure threshold. Changing these requires the admin key.

## Frontend

React Router with one route per page (`App.tsx`), a shared `Layout` with sidebar and
backend-health indicator, a typed API client (`api/client.ts`, `api/types.ts`) and a small
`useAsync` hook. No global state library: every page fetches what it shows, so all numbers
are live backend data. Recharts renders the dashboard and analysis charts.
