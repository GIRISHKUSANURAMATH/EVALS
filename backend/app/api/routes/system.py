"""Dashboard metrics, categories, settings and admin endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.database.session import Base, get_db
from app.models import Category, Cluster, EvalExample, Failure, IngestionJob, LogRecord, Trace
from app.privacy.redactor import RedactionConfig, Redactor
from app.schemas.api import (
    CategoryCreate,
    CategoryOut,
    RedactionPreviewRequest,
    RedactionPreviewResponse,
    SettingsPatch,
)
from app.services.datasets import ensure_builtin_categories
from app.services.settings_service import RuntimeSettings, get_runtime_settings, update_runtime_settings

router = APIRouter(tags=["system"])


@router.get("/dashboard/metrics")
def dashboard_metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    """All values are computed from the database on every request."""
    jobs_total = db.scalar(select(func.count(IngestionJob.id))) or 0
    jobs_ok = db.scalar(select(func.count(IngestionJob.id)).where(IngestionJob.status == "completed")) or 0
    logs = db.scalar(select(func.coalesce(func.sum(IngestionJob.total_records), 0))) or 0
    traces = db.scalar(select(func.count(Trace.id))) or 0
    dup = db.scalar(select(func.count(Trace.id)).where(Trace.duplicate_of_id.is_not(None))) or 0
    failed_traces = db.scalar(select(func.count(Trace.id)).where(Trace.status == "failed")) or 0
    failures = db.scalar(select(func.count(Failure.id))) or 0
    examples = db.scalar(select(func.count(EvalExample.id))) or 0
    approved = db.scalar(select(func.count(EvalExample.id)).where(EvalExample.review_status == "approved")) or 0
    avg_latency = db.scalar(select(func.avg(LogRecord.latency_ms)).where(LogRecord.latency_ms.is_not(None)))
    valid = db.scalar(select(func.coalesce(func.sum(IngestionJob.valid_records), 0))) or 0

    failures_by_type = [
        {"name": t, "observed": int(o or 0), "heuristic": int(h or 0)}
        for t, o, h in db.execute(
            select(
                Failure.failure_type,
                func.sum(case((Failure.evidence == "observed", 1), else_=0)),
                func.sum(case((Failure.evidence == "heuristic", 1), else_=0)),
            )
            .group_by(Failure.failure_type)
            .order_by(func.count().desc())
        ).all()
    ]
    examples_by_category = [
        {"name": c, "count": n}
        for c, n in db.execute(
            select(EvalExample.category, func.count()).group_by(EvalExample.category).order_by(func.count().desc())
        ).all()
    ]
    review_breakdown = {
        s: n
        for s, n in db.execute(
            select(EvalExample.review_status, func.count()).group_by(EvalExample.review_status)
        ).all()
    }
    trace_status = {s: n for s, n in db.execute(select(Trace.status, func.count()).group_by(Trace.status)).all()}

    # Latency histogram buckets (ms).
    edges = [0, 500, 1000, 2000, 5000, 10000, 30000]
    buckets = []
    for lo, hi in zip(edges, edges[1:] + [None], strict=True):
        cond = LogRecord.latency_ms >= lo
        if hi is not None:
            cond = cond & (LogRecord.latency_ms < hi)
        n = db.scalar(select(func.count(LogRecord.id)).where(cond)) or 0
        buckets.append({"bucket": f"{lo / 1000:g}-{hi / 1000:g}s" if hi else f">{lo / 1000:g}s", "count": n})

    recent_jobs = [
        {
            "id": j.id,
            "filename": j.filename,
            "status": j.status,
            "total_records": j.total_records,
            "trace_count": j.trace_count,
            "created_at": j.created_at.isoformat(),
        }
        for j in db.scalars(select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(5))
    ]
    return {
        "total_logs": int(logs),
        "valid_logs": int(valid),
        "total_traces": traces,
        "candidate_examples": examples,
        "approved_examples": approved,
        "detected_failures": failures,
        "failed_traces": failed_traces,
        "duplicate_percentage": round(100 * dup / traces, 2) if traces else 0.0,
        "average_latency_ms": round(float(avg_latency), 1) if avg_latency is not None else None,
        "processing_success_rate": round(100 * jobs_ok / jobs_total, 2) if jobs_total else None,
        "jobs_total": jobs_total,
        "clusters": db.scalar(select(func.count(Cluster.id))) or 0,
        "failures_by_type": failures_by_type,
        "examples_by_category": examples_by_category,
        "review_breakdown": review_breakdown,
        "trace_status": trace_status,
        "latency_histogram": buckets,
        "recent_jobs": recent_jobs,
    }


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.is_builtin.desc(), Category.name)))


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(req: CategoryCreate, db: Session = Depends(get_db)) -> Category:
    if db.scalar(select(Category).where(Category.name == req.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Category already exists")
    cat = Category(name=req.name, description=req.description, is_builtin=False)
    db.add(cat)
    db.commit()
    return cat


@router.get("/settings", response_model=RuntimeSettings)
def read_settings(db: Session = Depends(get_db)) -> RuntimeSettings:
    return get_runtime_settings(db)


@router.put("/settings", response_model=RuntimeSettings, dependencies=[Depends(require_admin)])
def write_settings(req: SettingsPatch, db: Session = Depends(get_db)) -> RuntimeSettings:
    try:
        return update_runtime_settings(db, req.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc).splitlines()[0]) from exc


@router.post("/privacy/preview", response_model=RedactionPreviewResponse)
def redaction_preview(req: RedactionPreviewRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    """Try the current redaction rules on sample text. Nothing is stored or logged."""
    rs = get_runtime_settings(db)
    r = Redactor(
        RedactionConfig(
            redact_ip_addresses=rs.redact_ip_addresses,
            sensitive_fields=set(rs.sensitive_fields),
            custom_patterns=dict(rs.custom_patterns),
        )
    )
    res = r.redact_text(req.text)
    return {"redacted": res.text, "counts": dict(res.counts)}


@router.post("/admin/reset", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def reset_database(db: Session = Depends(get_db)) -> None:
    """Delete all ingested data, datasets and custom categories."""
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == "alembic_version":
            continue
        db.execute(text(f"DELETE FROM {table.name}"))  # noqa: S608 - table names come from metadata
    db.commit()
    ensure_builtin_categories(db)
