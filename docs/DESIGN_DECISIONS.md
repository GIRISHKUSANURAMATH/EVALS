# Design decisions

## 1. Never fabricate ground truth

Production logs record what the model said, not what it should have said. Treating the
production answer as the expected answer would turn every eval into "the model agrees with
itself". So `expected_output_source` has three explicit states (`none`, `candidate`,
`human_approved`), every example stores a rationale for its expected output, and only the
review workflow can promote an answer to `human_approved`.

## 2. Evidence levels on every failure

A timeout recorded in the log is a fact; a "repetitive answer" is an opinion. Mixing them
would make failure counts untrustworthy. Every signal is `observed` or `heuristic`, the UI
colours them differently, confidence scores differ, and the detector never labels an answer
as factually wrong. "Hallucination" is only raised when user feedback in the log says so.

## 3. Deterministic local processing by default

TF-IDF + scikit-learn run on any laptop, need no downloads, and produce the same output for
the same input (tested in `test_reprocessing_is_deterministic`). Sentence-transformers
embeddings are an opt-in upgrade with automatic fallback; the optional LLM suggester is a
`Protocol` with a no-op default, so nothing calls a paid API unless configured.

## 4. Dedup within the same outcome

Merging "How do I reset my password?" that succeeded with the same question that timed out
would hide a failure. Traces are partitioned by outcome signature before similarity matching.

## 5. Pure pipeline modules, thin services

Stages take and return dataclasses with no DB or HTTP dependency. This keeps unit tests
fast, lets the benchmark time each stage in isolation, and makes it possible to move the
pipeline into a worker later without rewriting it.

## 6. Synchronous processing

A 25 MB upload processes in seconds (see benchmarks), so a job queue would add operational
complexity (Redis, worker process) with little benefit for a local tool. Each stage still
records a `ProcessingEvent`, so moving to background jobs later only changes the trigger.

## 7. SQLite first, PostgreSQL-compatible

SQLite needs zero setup on Windows. UUID string keys, generic JSON columns and Alembic
migrations keep the schema portable to PostgreSQL by changing `EVALS_DATABASE_URL`.

## 8. Explainable quality score

A single number invites blind trust. The score is a weighted average of seven named factors,
each returned with its weight and a sentence explaining its value, and shown as bars in the
review screen. Re-scoring after review means approved examples rise and rejected ones fall.

## 9. Admin key off by default

Destructive operations are disabled unless an admin key is configured, rather than open by
default. A fresh install cannot be wiped by a stray request.

## 10. Silhouette-chosen k

Users rarely know how many topics their traffic has. K-means picks k by maximum silhouette
score on a bounded sample, keeping clustering cheap while avoiding a magic constant. DBSCAN
is available when topic sizes are very uneven.
