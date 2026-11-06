"""Orchestrates the full processing pipeline and persists results.

Stages: validate -> parse/normalize -> redact -> reconstruct -> detect failures ->
deduplicate -> cluster. Each stage records a ProcessingEvent with timing so the
Processing Pipeline page can show exactly what happened.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.evaluation.generator import FailureView, has_positive_feedback, primary_failure
from app.ingestion.parsers import parse_content
from app.ingestion.schema import ParseResult
from app.ingestion.validation import UploadValidationError, validate_upload
from app.models import Cluster, Failure, IngestionJob, LogRecord, ProcessingEvent, Trace
from app.models.entities import utcnow
from app.privacy.pipeline import redact_record
from app.privacy.redactor import RedactionConfig, Redactor
from app.processing.clustering import ClusteringConfig, ClusterItem, cluster_items
from app.processing.dedup import DedupConfig, DedupItem, DedupResult, deduplicate
from app.processing.failures import OBSERVED, DetectionConfig, detect_failures, trace_status
from app.processing.reconstruction import reconstruct_traces
from app.services.settings_service import RuntimeSettings, get_runtime_settings

logger = get_logger(__name__)


def outcome_signature(fails: list[Any]) -> str:
    pf = primary_failure([FailureView(f.failure_type, f.evidence) for f in fails])
    return f"{pf.evidence}:{pf.failure_type}" if pf else "ok"


def _hashas_positive_feedback(meta: dict[str, Any]) -> bool:
    return has_positive_feedback(meta)


class _StageRecorder:
    def __init__(self, db: Session, job: IngestionJob) -> None:
        self.db = db
        self.job = job
        self.timings: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[dict[str, Any]]:
        details: dict[str, Any] = {}
        start = time.perf_counter()
        try:
            yield details
        except Exception as exc:
            ms = (time.perf_counter() - start) * 1000
            self.db.add(
                ProcessingEvent(
                    job_id=self.job.id,
                    stage=name,
                    status="failed",
                    message=str(exc)[:500],
                    duration_ms=ms,
                    details=details,
                )
            )
            raise
        ms = (time.perf_counter() - start) * 1000
        self.timings[name] = round(ms, 2)
        message = details.pop("message", "")
        self.db.add(
            ProcessingEvent(
                job_id=self.job.id, stage=name, status="completed", message=message, duration_ms=ms, details=details
            )
        )


def process_upload(
    db: Session, filename: str, content: bytes, source: str = "upload", progress: Callable[[str], None] | None = None
) -> IngestionJob:
    """Validate and process an uploaded file. Raises UploadValidationError for bad files
    (no job is created); processing errors after validation mark the job as failed."""
    settings = get_settings()
    upload = validate_upload(filename, content, settings.max_upload_bytes)
    job = IngestionJob(
        filename=filename,
        file_format=upload.file_format,
        source=source,
        status="processing",
        file_size_bytes=upload.size_bytes,
    )
    db.add(job)
    db.commit()
    logger.info("job %s: processing %s file (%d bytes)", job.id, upload.file_format, upload.size_bytes)
    rec = _StageRecorder(db, job)
    try:
        with rec.stage("validation") as d:
            d["message"] = f"{upload.file_format.upper()} file accepted ({upload.size_bytes} bytes)"
        with rec.stage("parsing") as d:
            parsed = parse_content(upload.text, upload.file_format, settings.max_records_per_upload)
            d.update(total=parsed.total_lines, parsed=len(parsed.records), malformed=len(parsed.malformed))
            d["message"] = f"{len(parsed.records)} records parsed, {len(parsed.malformed)} malformed"
        _run_stages(db, job, parsed, get_runtime_settings(db), rec, settings.preserve_raw_content)
        job.status = "completed"
        job.completed_at = utcnow()
        job.stats = dict(job.stats or {}) | {"stage_timings_ms": rec.timings}
        db.commit()
    except UploadValidationError as exc:
        db.rollback()
        _mark_failed(db, job.id, str(exc))
        raise
    except Exception as exc:  # pragma: no cover - unexpected processing failure
        db.rollback()
        logger.exception("job %s failed", job.id)
        _mark_failed(db, job.id, f"Processing failed: {type(exc).__name__}")
        raise
    db.refresh(job)
    return job


def _mark_failed(db: Session, job_id: str, message: str) -> None:
    job = db.get(IngestionJob, job_id)
    if job:
        job.status = "failed"
        job.error_message = message
        job.completed_at = utcnow()
        db.add(ProcessingEvent(job_id=job_id, stage="pipeline", status="failed", message=message))
        db.commit()


def _run_stages(
    db: Session, job: IngestionJob, parsed: ParseResult, rs: RuntimeSettings, rec: _StageRecorder, preserve_raw: bool
) -> None:
    redactor = Redactor(
        RedactionConfig(
            redact_ip_addresses=rs.redact_ip_addresses,
            sensitive_fields=set(rs.sensitive_fields),
            custom_patterns=dict(rs.custom_patterns),
        )
    )
    with rec.stage("redaction") as d:
        totals: Counter[str] = Counter()
        for r in parsed.records:
            totals.update(redact_record(r, redactor, preserve_raw=preserve_raw))
        job.redaction_counts = dict(totals)
        d.update(redactions=sum(totals.values()), by_type=dict(totals))
        d["message"] = f"{sum(totals.values())} sensitive values redacted"

    with rec.stage("normalization") as d:
        job.total_records = parsed.total_lines
        job.valid_records = parsed.valid_count
        job.invalid_records = parsed.invalid_count
        d.update(
            valid=job.valid_records,
            invalid=job.invalid_records,
            malformed_examples=[{"line": ln, "reason": reason} for ln, reason in parsed.malformed[:20]],
        )
        d["message"] = f"{job.valid_records} valid, {job.invalid_records} invalid records"

    with rec.stage("reconstruction") as d:
        traces = reconstruct_traces(parsed.records)
        d.update(
            traces=len(traces),
            multi_turn=sum(1 for t in traces if len(t.turns) > 1),
            incomplete=sum(1 for t in traces if not t.is_complete),
        )
        d["message"] = f"{len(traces)} traces reconstructed"

    with rec.stage("failure_detection") as d:
        failures = detect_failures(
            traces,
            DetectionConfig(latency_threshold_ms=rs.latency_threshold_ms, repeated_failure_min=rs.repeated_failure_min),
        )
        all_f = [f for fl in failures.values() for f in fl]
        d.update(
            total=len(all_f),
            observed=sum(1 for f in all_f if f.evidence == OBSERVED),
            heuristic=sum(1 for f in all_f if f.evidence != OBSERVED),
            by_type=dict(Counter(f.failure_type for f in all_f)),
        )
        d["message"] = f"{len(all_f)} failure signals ({d['observed']} observed, {d['heuristic']} heuristic)"

    with rec.stage("deduplication") as d:
        # Duplicates are judged *within the same outcome*: a successful answer and a timeout for
        # the same question are both useful eval examples, so they are never merged.
        partitions: dict[str, list[DedupItem]] = {}
        for t in traces:
            sig = outcome_signature(failures[t.trace_key])
            focus = t.focus() if t.turns else None
            partitions.setdefault(sig, []).append(
                DedupItem(
                    key=t.trace_key,
                    text=(focus.user_input or "") if focus else "",
                    priority=1 if focus is not None and _hashas_positive_feedback(focus.metadata) else 0,
                )
            )
        dedup: dict[str, DedupResult] = {}
        backend = "disabled"
        dcfg = DedupConfig(
            similarity_threshold=rs.similarity_threshold,
            use_semantic=rs.semantic_dedup,
            use_embeddings=rs.use_embeddings,
        )
        for part in partitions.values():
            res, used = deduplicate(part, dcfg)
            dedup.update(res)
            if used not in ("none", "disabled"):
                backend = used
        dups = sum(1 for r in dedup.values() if r.duplicate_of)
        d.update(
            duplicates=dups, backend=backend, by_method=dict(Counter(r.method for r in dedup.values() if r.method))
        )
        d["message"] = f"{dups} duplicates found ({backend})"

    # Persist traces before clustering so clusters can reference them.
    with rec.stage("persistence") as d:
        key_to_trace: dict[str, Trace] = {}
        for t in traces:
            focus = t.focus()
            fl = failures[t.trace_key]
            dr = dedup.get(t.trace_key)
            row = Trace(
                job_id=job.id,
                trace_key=t.trace_key[:255],
                start_time=t.start_time,
                end_time=t.end_time,
                turn_count=len(t.turns),
                total_latency_ms=t.total_latency_ms,
                total_tokens=t.total_tokens,
                models=t.models,
                status=trace_status(fl),
                is_complete=t.is_complete,
                has_missing_response=t.has_missing_response,
                system_prompt=t.system_prompt,
                input_text=focus.user_input or "",
                output_text=focus.assistant_response,
                conversation=[x.to_dict() for x in t.turns],
                failure_types=sorted({f.failure_type for f in fl}),
                metadata_=t.metadata | {"focal_turn": focus.index, "context": t.context_before_focus()},
                normalized_hash=dr.normalized_hash if dr else "",
                duplicate_method=dr.method if dr else None,
                duplicate_score=dr.score if dr else 0.0,
                duplicate_group_size=dr.group_size if dr else 1,
            )
            db.add(row)
            key_to_trace[t.trace_key] = row
            for f in fl:
                row.failures.append(
                    Failure(
                        job_id=job.id,
                        failure_type=f.failure_type,
                        evidence=f.evidence,
                        severity=f.severity,
                        detail=f.detail,
                        turn_index=f.turn_index,
                    )
                )
        db.flush()
        for key, dr in dedup.items():
            if dr.duplicate_of:
                key_to_trace[key].duplicate_of_id = key_to_trace[dr.duplicate_of].id
        line_to_trace = {ln: key_to_trace[t.trace_key].id for t in traces for ln in t.record_lines}
        db.bulk_save_objects(
            [
                LogRecord(
                    job_id=job.id,
                    trace_id=line_to_trace.get(r.line_number),
                    line_number=r.line_number,
                    trace_key=(r.trace_id or "")[:255] or None,
                    request_id=r.request_id,
                    timestamp=r.timestamp,
                    user_input=r.user_input,
                    system_prompt=r.system_prompt,
                    assistant_response=r.assistant_response,
                    model=r.model,
                    latency_ms=r.latency_ms,
                    prompt_tokens=r.prompt_tokens,
                    completion_tokens=r.completion_tokens,
                    total_tokens=r.total_tokens,
                    status=r.status,
                    error_type=r.error_type,
                    error_message=r.error_message,
                    metadata_=r.metadata,
                    is_valid=r.is_valid,
                    validation_errors=r.validation_errors,
                    redaction_count=r.redaction_count,
                    raw_payload=r.raw_payload,
                )
                for r in parsed.records
            ]
        )
        job.trace_count = len(traces)
        d.update(traces=len(traces), records=len(parsed.records))
        d["message"] = f"{len(traces)} traces and {len(parsed.records)} records stored"

    with rec.stage("clustering") as d:
        reps = [t for t in traces if not dedup.get(t.trace_key) or not dedup[t.trace_key].duplicate_of]
        citems = [
            ClusterItem(
                key=t.trace_key, text=t.focus().user_input or "", failed=key_to_trace[t.trace_key].status == "failed"
            )
            for t in reps
        ]
        results = cluster_items(citems, ClusteringConfig(method=rs.clustering_method, max_clusters=rs.max_clusters))
        rep_to_members: dict[str, list[str]] = {}
        for key, dr in dedup.items():
            if dr.duplicate_of:
                rep_to_members.setdefault(dr.duplicate_of, []).append(key)
        for cr in results:
            members = list(cr.member_keys) + [m for k in cr.member_keys for m in rep_to_members.get(k, [])]
            cluster = Cluster(
                job_id=job.id,
                label=cr.label[:255],
                method=cr.method,
                size=len(members),
                top_terms=cr.top_terms,
                failure_rate=cr.failure_rate,
                representative_trace_id=key_to_trace[cr.representative_key].id,
            )
            db.add(cluster)
            db.flush()
            for key in members:
                key_to_trace[key].cluster_id = cluster.id
        d.update(clusters=len(results), method=rs.clustering_method)
        d["message"] = f"{len(results)} clusters ({rs.clustering_method})"

    job.stats = {
        "failures_observed": sum(1 for fl in failures.values() for f in fl if f.evidence == OBSERVED),
        "failures_heuristic": sum(1 for fl in failures.values() for f in fl if f.evidence != OBSERVED),
        "duplicates": sum(1 for r in dedup.values() if r.duplicate_of),
        "similarity_backend": backend,
    }
