# Data pipeline

Every stage below is a separate module with its own tests. Stage timings and counts are
stored as `processing_events` and shown on the Processing Pipeline page.

## 1. Validation — `ingestion/validation.py`

Rejects with a clear message (HTTP 4xx) when the file is: empty, larger than
`EVALS_MAX_UPLOAD_MB` (default 25), an unsupported extension, binary (NUL bytes), or not
valid UTF-8 (a UTF-8 BOM is accepted). Supported extensions: `.jsonl .ndjson .json .csv
.log .txt`. A `.log`/`.txt` file whose first line is a JSON object is treated as JSONL.

## 2. Parsing and normalisation — `ingestion/parsers.py`, `ingestion/normalizer.py`

| Format | Accepted shapes |
| --- | --- |
| JSONL | one JSON object per line; bad lines are counted as malformed with line numbers |
| JSON | an array, or an object holding the array under `logs/records/data/items/events/traces/interactions`, or a single object |
| CSV | header row; parsed with pandas as strings so nothing is silently coerced |
| OpenAI style | `messages: [...]` (system/user/assistant) and `choices[0].message.content`, `usage`, `model` |
| Generic app log | `2026-01-01T10:00:00Z INFO key=value key2="quoted value"` lines |

Each record maps to a `NormalizedRecord` via field aliases (e.g. `trace_id | conversation_id
| session_id | thread_id`, `response | output | completion | answer`, `latency_ms |
duration_ms | latency` with seconds→ms conversion). Unknown fields are kept in `metadata`.
A record with neither input nor output nor error is marked invalid and reported.
A record nested more than 64 levels deep is reported as malformed (a document too deep for the
JSON parser is rejected with 422). Caps: `EVALS_MAX_RECORDS_PER_UPLOAD` (default 200,000).

## 3. Privacy and redaction — `privacy/redactor.py`

Runs **before** persistence on input, response, system prompt, error message and every
string in metadata. Ordered rules (more specific first):

private-key blocks → JWTs → OpenAI / AWS / GitHub / Slack / Google / Stripe keys → bearer
tokens → `password=`/`api_key:`-style assignments → emails → credit cards (**Luhn-validated**)
→ SSNs → phone numbers (international and US formats) → IPv4 (**octet-validated**, so version
numbers like `1.2.3.4000` are not touched) → IPv6.

Metadata keys matching the configurable sensitive list (`password`, `secret`, `token`,
`authorization`, `api_key`, …) have their whole value masked. Custom named regexes can be
added on the Settings page (validated, length-capped). Redaction counts per type are stored
on the job — the values themselves are not. Raw text is only kept when
`EVALS_PRESERVE_RAW_CONTENT=true`, and is never returned by exports.

## 4. Interaction reconstruction — `processing/reconstruction.py`

- Groups records by trace id (falling back to request id, then line number).
- Merges split request/response records that share a request id into one turn.
- Orders turns by timestamp (records without one go last), then by line number.
- Produces a `ReconstructedTrace` with turns, system prompt, `is_complete`
  and `has_missing_response` flags. After failure detection a **focus turn** is chosen: the first turn
  with an observed failure, else the first turn with any signal, else the last turn. It
  supplies the example input; earlier turns become conversation context.

## 5. Failure detection — `processing/failures.py`

Every signal carries an **evidence** level.

| Failure type | Evidence | Rule |
| --- | --- | --- |
| application_error | observed | error status / error type / error message present |
| timeout | observed | status or error mentions timeout / deadline exceeded |
| empty_response | observed | success status but blank response |
| missing_response | observed | user turn with no response and no error |
| malformed_structured_output | observed | JSON requested (response_format or system prompt) and response does not parse |
| tool_call_failure | observed | a tool call in metadata reports an error |
| truncated_output | observed | `finish_reason` = length |
| negative_feedback | observed | user feedback is negative |
| hallucination_candidate | observed | negative feedback whose text says fabricated / incorrect / made up |
| repeated_failure | observed | same normalised input failed in ≥ N traces (default 3) |
| excessive_latency | heuristic | latency above threshold (default 10 s) |
| repetitive_output | heuristic | repeated 4-gram ratio above threshold |
| canned_response | heuristic | identical response returned for many different inputs |
| refusal | heuristic | response opens with refusal phrasing |
| edge_case_input | heuristic | very long, empty, or mostly non-text input |

The detector **never** claims a response is factually wrong. `hallucination_candidate` is
only raised when the log itself contains user feedback saying so, and is still a candidate
for human verification.

## 6. Deduplication — `processing/dedup.py`, `processing/embeddings.py`

Deduplication runs within one upload (ingestion job); identical traffic arriving in two
separate uploads is not merged.

Traces are partitioned by **outcome signature** first (e.g. `observed:timeout` vs `ok`), so a
successful answer and a timeout for the same question are never merged: both are useful.

Within a partition: exact hash → normalised-text hash (case, whitespace, punctuation) →
cosine similarity ≥ threshold (default 0.90) using TF-IDF character n-grams, or
sentence-transformers embeddings when `use_embeddings` is on **and** the package is
installed (otherwise it falls back silently and reports the backend used). Matches are
merged with union-find; the representative prefers traces with positive feedback.
Each trace stores `duplicate_of_id`, `duplicate_score` and group size.

## 7. Clustering — `processing/clustering.py`

Non-duplicate traces of each upload are clustered at the end of that upload's pipeline
(duplicates inherit their representative's cluster). TF-IDF word vectors, then:

- **K-means** (default): k chosen by maximum cosine silhouette score on a bounded sample,
  up to `max_clusters`.
- **DBSCAN**: cosine distance, configurable `eps` / `min_samples`; noise becomes its own group.

Each cluster stores its size, top TF-IDF terms (used as the label) and the trace closest to
the centroid as its representative.

## 8. Example generation — `evaluation/generator.py`

One example per selected trace (duplicates excluded by default). Category = mapping of the
primary failure type (`evaluation/categories.py`), or `correctness` for successful traces.
Expected-output provenance:

| `expected_output_source` | When |
| --- | --- |
| `none` | default — no defensible reference exists |
| `candidate` | a reference field in the log (`expected_output`, `reference_answer`, `ground_truth`, …), **or** a successful answer with explicit positive feedback, **or** an optional LLM suggestion |
| `human_approved` | only set by a reviewer approving with an expected output |

Each example carries a `rationale` explaining where its expected output came from.

## 9. Quality scoring — `evaluation/scoring.py`

Weighted average of seven named factors, each returned with value, weight and explanation:

| Factor | Weight |
| --- | ---: |
| completeness | 0.20 |
| duplicate_probability | 0.15 |
| input_validity | 0.15 |
| output_validity | 0.15 |
| label_confidence | 0.15 |
| trace_completeness | 0.10 |
| review_status | 0.10 |

Examples are re-scored whenever they are edited or reviewed.

## 10. Review, versioning, export

See [ARCHITECTURE.md](ARCHITECTURE.md#request-flow-dataset--review--export) and [API.md](API.md).
