"""Dataset generation, versioning, review and export services."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.evaluation.categories import BUILTIN_CATEGORIES
from app.evaluation.exporters import ExportFormat, example_to_record, render, validate_records
from app.evaluation.generator import FailureView, GenerationConfig, TraceSnapshot, generate_examples
from app.evaluation.llm import get_suggester
from app.evaluation.scoring import ScoringInput, score_example
from app.models import Category, Dataset, DatasetVersion, EvalExample, ReviewAnnotation, Trace
from app.models.entities import utcnow


class NotFoundError(LookupError):
    pass


class ConflictError(ValueError):
    pass


# ----------------------------------------------------------------------------- categories
def ensure_builtin_categories(db: Session) -> None:
    existing = set(db.scalars(select(Category.name)))
    for name, desc in BUILTIN_CATEGORIES.items():
        if name not in existing:
            db.add(Category(name=name, description=desc, is_builtin=True))
    db.commit()


def category_names(db: Session) -> set[str]:
    return set(db.scalars(select(Category.name)))


# ----------------------------------------------------------------------------- generation
def _snapshot(t: Trace) -> TraceSnapshot:
    focal_idx = (t.metadata_ or {}).get("focal_turn", len(t.conversation) - 1)
    focal_meta: dict[str, Any] = {}
    if t.conversation and 0 <= focal_idx < len(t.conversation):
        focal_meta = t.conversation[focal_idx].get("metadata") or {}
    return TraceSnapshot(
        id=t.id,
        trace_key=t.trace_key,
        job_id=t.job_id,
        input_text=t.input_text or "",
        output_text=t.output_text,
        system_prompt=t.system_prompt,
        context=(t.metadata_ or {}).get("context", []),
        start_time=t.start_time,
        status=t.status,
        is_complete=t.is_complete,
        has_missing_response=t.has_missing_response,
        duplicate_of_id=t.duplicate_of_id,
        duplicate_score=t.duplicate_score,
        duplicate_group_size=t.duplicate_group_size,
        models=list(t.models or []),
        total_latency_ms=t.total_latency_ms,
        metadata={k: v for k, v in (t.metadata_ or {}).items() if k not in ("context", "focal_turn")},
        focal_metadata=focal_meta,
        failures=[FailureView(f.failure_type, f.evidence, f.detail) for f in t.failures],
        cluster_label=t.cluster.label if t.cluster else None,
    )


def generate_dataset(
    db: Session, name: str, description: str, job_ids: list[str] | None, cfg: GenerationConfig
) -> Dataset:
    if cfg.categories:
        unknown = set(cfg.categories) - category_names(db)
        if unknown:
            raise ConflictError(f"Unknown categories: {', '.join(sorted(unknown))}")
    q = select(Trace).options(selectinload(Trace.failures), selectinload(Trace.cluster))
    if job_ids:
        q = q.where(Trace.job_id.in_(job_ids))
    traces = list(db.scalars(q))
    if not traces:
        raise ConflictError("No processed traces found. Upload logs or load the sample dataset first.")
    drafts = generate_examples([_snapshot(t) for t in traces], cfg, get_suggester(get_settings().llm_provider))
    ds = Dataset(
        name=name,
        description=description,
        source_job_ids=sorted({t.job_id for t in traces}),
        generation_config={
            "include_successful": cfg.include_successful,
            "exclude_duplicates": cfg.exclude_duplicates,
            "categories": cfg.categories,
            "min_quality": cfg.min_quality,
            "max_examples": cfg.max_examples,
            "traces_considered": len(traces),
        },
    )
    db.add(ds)
    db.flush()
    for d in drafts:
        db.add(
            EvalExample(
                dataset_id=ds.id,
                source_trace_id=d.source_trace_id,
                source_trace_key=d.source_trace_key,
                source_job_id=d.source_job_id,
                source_timestamp=d.source_timestamp,
                input=d.input,
                system_prompt=d.system_prompt,
                context=d.context,
                actual_output=d.actual_output,
                expected_output=d.expected_output,
                expected_output_source=d.expected_output_source,
                expected_output_rationale=d.expected_output_rationale,
                category=d.category,
                failure_type=d.failure_type,
                failure_evidence=d.failure_evidence,
                metadata_=d.metadata,
                confidence_score=d.confidence_score,
                quality_score=d.quality_score,
                quality_factors=d.quality_factors,
            )
        )
    db.flush()
    _create_version(db, ds, "Initial generated version")
    db.commit()
    db.refresh(ds)
    return ds


# ----------------------------------------------------------------------------- versions
def _snapshot_examples(examples: list[EvalExample]) -> list[dict[str, Any]]:
    out = []
    for ex in sorted(examples, key=lambda e: e.id):
        out.append(
            {
                "id": ex.id,
                "input": ex.input,
                "expected_output": ex.expected_output,
                "expected_output_source": ex.expected_output_source,
                "actual_output": ex.actual_output,
                "category": ex.category,
                "failure_type": ex.failure_type,
                "review_status": ex.review_status,
                "quality_score": ex.quality_score,
            }
        )
    return out


def _create_version(db: Session, ds: Dataset, notes: str) -> DatasetVersion:
    examples = list(db.scalars(select(EvalExample).where(EvalExample.dataset_id == ds.id)))
    snap = _snapshot_examples(examples)
    checksum = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()
    last = db.scalar(select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == ds.id)) or 0
    v = DatasetVersion(
        dataset_id=ds.id,
        version_number=last + 1,
        example_count=len(examples),
        approved_count=sum(1 for e in examples if e.review_status == "approved"),
        notes=notes,
        checksum=checksum,
        snapshot=snap,
    )
    db.add(v)
    ds.current_version = last + 1
    return v


def create_version(db: Session, dataset_id: str, notes: str) -> DatasetVersion:
    ds = get_dataset(db, dataset_id)
    v = _create_version(db, ds, notes)
    db.commit()
    return v


def get_dataset(db: Session, dataset_id: str) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise NotFoundError("Dataset not found")
    return ds


def dataset_stats(db: Session, dataset_id: str) -> dict[str, Any]:
    rows = db.execute(
        select(EvalExample.review_status, EvalExample.category, func.count(), func.avg(EvalExample.quality_score))
        .where(EvalExample.dataset_id == dataset_id)
        .group_by(EvalExample.review_status, EvalExample.category)
    ).all()
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    total = 0
    weighted_q = 0.0
    for status, cat, n, avg_q in rows:
        by_status[status] = by_status.get(status, 0) + n
        by_category[cat] = by_category.get(cat, 0) + n
        total += n
        weighted_q += (avg_q or 0) * n
    exp_rows = db.execute(
        select(EvalExample.expected_output_source, func.count())
        .where(EvalExample.dataset_id == dataset_id)
        .group_by(EvalExample.expected_output_source)
    ).all()
    covered = sum(1 for c in BUILTIN_CATEGORIES if by_category.get(c))
    return {
        "total": total,
        "by_status": by_status,
        "by_category": by_category,
        "by_expected_source": {s: n for s, n in exp_rows},
        "avg_quality": round(weighted_q / total, 4) if total else 0.0,
        "category_coverage": round(covered / len(BUILTIN_CATEGORIES), 4),
    }


def delete_dataset(db: Session, dataset_id: str) -> None:
    ds = get_dataset(db, dataset_id)
    db.delete(ds)
    db.commit()


# ----------------------------------------------------------------------------- examples
def query_examples(
    db: Session,
    dataset_id: str,
    status: str | None,
    category: str | None,
    search: str | None,
    failure_type: str | None,
    page: int,
    page_size: int,
    sort: str = "quality_desc",
) -> tuple[list[EvalExample], int]:
    q = select(EvalExample).where(EvalExample.dataset_id == dataset_id)
    if status:
        q = q.where(EvalExample.review_status == status)
    if category:
        q = q.where(EvalExample.category == category)
    if failure_type:
        q = q.where(EvalExample.failure_type == failure_type)
    if search:
        like = f"%{search.strip()[:200]}%"
        q = q.where(
            or_(
                EvalExample.input.ilike(like),
                EvalExample.actual_output.ilike(like),
                EvalExample.expected_output.ilike(like),
                EvalExample.source_trace_key.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    order: Any = {
        "quality_desc": EvalExample.quality_score.desc(),
        "quality_asc": EvalExample.quality_score.asc(),
        "newest": EvalExample.source_timestamp.desc(),
        "oldest": EvalExample.source_timestamp.asc(),
    }.get(sort, EvalExample.quality_score.desc())
    items = list(db.scalars(q.order_by(order, EvalExample.id).offset((page - 1) * page_size).limit(page_size)))
    return items, total


def get_example(db: Session, example_id: str) -> EvalExample:
    ex = db.get(EvalExample, example_id)
    if ex is None:
        raise NotFoundError("Example not found")
    return ex


def _rescore(db: Session, ex: EvalExample) -> None:
    trace = db.get(Trace, ex.source_trace_id) if ex.source_trace_id else None
    score, factors = score_example(
        ScoringInput(
            input_text=ex.input,
            actual_output=ex.actual_output,
            expected_output=ex.expected_output,
            expected_output_source=ex.expected_output_source,
            failure_type=ex.failure_type,
            failure_evidence=ex.failure_evidence,
            has_metadata=bool(ex.metadata_),
            duplicate_group_size=trace.duplicate_group_size if trace else 1,
            duplicate_score=trace.duplicate_score if trace else 0.0,
            is_duplicate=bool(trace and trace.duplicate_of_id),
            trace_complete=trace.is_complete if trace else True,
            missing_response=trace.has_missing_response if trace else False,
            confidence=ex.confidence_score,
            review_status=ex.review_status,
        )
    )
    ex.quality_score, ex.quality_factors = score, factors


def update_example(db: Session, example_id: str, changes: dict[str, Any], reviewer: str) -> EvalExample:
    """PATCH: edit expected output, category or notes. Recorded in annotation history."""
    ex = get_example(db, example_id)
    if "category" in changes and changes["category"] is not None and changes["category"] not in category_names(db):
        raise ConflictError(f"Unknown category: {changes['category']}")
    prev: dict[str, Any] = {}
    new: dict[str, Any] = {}
    for field in ("expected_output", "category", "reviewer_notes"):
        if field in changes and changes[field] is not None and getattr(ex, field) != changes[field]:
            prev[field] = getattr(ex, field)
            new[field] = changes[field]
            setattr(ex, field, changes[field])
    if not new:
        return ex
    if "expected_output" in new:
        # A human edit is still a candidate until the example is approved.
        ex.expected_output_source = "human_approved" if ex.review_status == "approved" else "candidate"
        ex.expected_output_rationale = f"Edited by reviewer '{reviewer}'."
        new["expected_output_source"] = ex.expected_output_source
    if "category" in new:
        ex.confidence_score = 1.0  # a human assigned it
    action = "edit" if "expected_output" in new else ("recategorize" if "category" in new else "note")
    db.add(ReviewAnnotation(example_id=ex.id, action=action, reviewer=reviewer, previous_values=prev, new_values=new))
    _rescore(db, ex)
    ex.updated_at = utcnow()
    db.commit()
    db.refresh(ex)
    return ex


_REVIEW_ACTIONS = {"approve": "approved", "reject": "rejected", "flag": "flagged", "reset": "pending"}


def review_example(
    db: Session,
    example_id: str,
    action: str,
    reviewer: str,
    note: str = "",
    expected_output: str | None = None,
    category: str | None = None,
) -> EvalExample:
    if action not in _REVIEW_ACTIONS:
        raise ConflictError(f"Unknown review action: {action}")
    ex = get_example(db, example_id)
    if category is not None and category not in category_names(db):
        raise ConflictError(f"Unknown category: {category}")
    prev: dict[str, Any] = {"review_status": ex.review_status}
    new: dict[str, Any] = {"review_status": _REVIEW_ACTIONS[action]}
    if expected_output is not None and expected_output != ex.expected_output:
        prev["expected_output"] = ex.expected_output
        new["expected_output"] = expected_output
        ex.expected_output = expected_output
    if category is not None and category != ex.category:
        prev["category"] = ex.category
        new["category"] = category
        ex.category = category
        ex.confidence_score = 1.0
    ex.review_status = _REVIEW_ACTIONS[action]
    if action == "approve" and ex.expected_output is not None:
        prev["expected_output_source"] = ex.expected_output_source
        ex.expected_output_source = "human_approved"
        ex.expected_output_rationale = f"Approved by reviewer '{reviewer}'."
        new["expected_output_source"] = "human_approved"
    elif action != "approve" and ex.expected_output_source == "human_approved":
        prev["expected_output_source"] = "human_approved"
        ex.expected_output_source = "candidate"
        new["expected_output_source"] = "candidate"
    if note:
        ex.reviewer_notes = note
    db.add(
        ReviewAnnotation(
            example_id=ex.id, action=action, reviewer=reviewer, previous_values=prev, new_values=new, note=note
        )
    )
    _rescore(db, ex)
    ex.updated_at = utcnow()
    db.commit()
    db.refresh(ex)
    return ex


# ----------------------------------------------------------------------------- export
def export_dataset(
    db: Session,
    dataset_id: str,
    fmt: ExportFormat,
    approved_only: bool,
    categories: list[str] | None,
    date_from: datetime | None,
    date_to: datetime | None,
    statuses: list[str] | None = None,
) -> tuple[str, int, dict[str, Any]]:
    ds = get_dataset(db, dataset_id)
    q = select(EvalExample).where(EvalExample.dataset_id == dataset_id)
    if approved_only:
        q = q.where(EvalExample.review_status == "approved")
    elif statuses:
        q = q.where(EvalExample.review_status.in_(statuses))
    if categories:
        q = q.where(EvalExample.category.in_(categories))
    if date_from:
        q = q.where(EvalExample.source_timestamp >= date_from)
    if date_to:
        q = q.where(EvalExample.source_timestamp <= date_to)
    examples = list(db.scalars(q.order_by(EvalExample.source_timestamp, EvalExample.id)))
    records = validate_records([example_to_record(e) for e in examples])
    manifest = {
        "dataset_id": ds.id,
        "dataset_name": ds.name,
        "version": ds.current_version,
        "exported_at": utcnow().isoformat(),
        "format": fmt,
        "example_count": len(records),
        "filters": {
            "approved_only": approved_only,
            "categories": categories,
            "statuses": statuses,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "source_job_ids": ds.source_job_ids,
        "generator": "EVALS",
        "notes": "expected_output_source distinguishes none / candidate / human_approved references.",
    }
    return render(records, fmt, manifest), len(records), manifest
