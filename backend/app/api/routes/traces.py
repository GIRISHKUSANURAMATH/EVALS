from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.session import get_db
from app.models import Cluster, Failure, Trace
from app.processing.failures import FAILURE_TYPES
from app.schemas.api import (
    ClusterOut,
    ClusterWithExamples,
    FailureSummary,
    FailureWithTrace,
    Page,
    TraceDetail,
    TraceSummary,
)

router = APIRouter(tags=["traces"])


@router.get("/traces", response_model=Page[TraceSummary])
def list_traces(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    job_id: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    failure_type: str | None = None,
    cluster_id: str | None = None,
    duplicates: str | None = Query(None, pattern="^(only|exclude)$"),
    search: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    q = select(Trace)
    if job_id:
        q = q.where(Trace.job_id == job_id)
    if status_filter:
        q = q.where(Trace.status == status_filter)
    if cluster_id:
        q = q.where(Trace.cluster_id == cluster_id)
    if failure_type:
        q = q.where(Trace.id.in_(select(Failure.trace_id).where(Failure.failure_type == failure_type)))
    if duplicates == "only":
        q = q.where(Trace.duplicate_of_id.is_not(None))
    elif duplicates == "exclude":
        q = q.where(Trace.duplicate_of_id.is_(None))
    if search:
        like = f"%{search}%"
        q = q.where(or_(Trace.input_text.ilike(like), Trace.output_text.ilike(like), Trace.trace_key.ilike(like)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(
        db.scalars(
            q.order_by(Trace.start_time.desc().nulls_last(), Trace.id).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/traces/{trace_id}", response_model=TraceDetail)
def get_trace(trace_id: str, db: Session = Depends(get_db)) -> Trace:
    t = db.scalar(select(Trace).options(selectinload(Trace.failures)).where(Trace.id == trace_id))
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found")
    return t


@router.get("/failures", response_model=Page[FailureWithTrace])
def list_failures(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    failure_type: str | None = None,
    evidence: str | None = Query(None, pattern="^(observed|heuristic)$"),
    severity: str | None = None,
    job_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    q = select(Failure, Trace.trace_key, Trace.input_text).join(Trace, Trace.id == Failure.trace_id)
    if failure_type:
        q = q.where(Failure.failure_type == failure_type)
    if evidence:
        q = q.where(Failure.evidence == evidence)
    if severity:
        q = q.where(Failure.severity == severity)
    if job_id:
        q = q.where(Failure.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.execute(q.order_by(Failure.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [
        FailureWithTrace.model_validate(
            {
                **{
                    c: getattr(f, c)
                    for c in (
                        "id",
                        "trace_id",
                        "job_id",
                        "failure_type",
                        "evidence",
                        "severity",
                        "detail",
                        "turn_index",
                    )
                },
                "trace_key": key,
                "input_text": text,
            }
        )
        for f, key, text in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/failures/summary", response_model=FailureSummary)
def failure_summary(job_id: str | None = None, db: Session = Depends(get_db)) -> dict[str, object]:
    q = select(Failure.failure_type, Failure.evidence, Failure.severity, func.count()).group_by(
        Failure.failure_type, Failure.evidence, Failure.severity
    )
    if job_id:
        q = q.where(Failure.job_id == job_id)
    by_type: dict[str, dict[str, object]] = {}
    by_sev: dict[str, int] = {}
    observed = heuristic = 0
    for ftype, ev, sev, n in db.execute(q).all():
        entry = by_type.setdefault(
            ftype, {"failure_type": ftype, "count": 0, "evidence": ev, "description": FAILURE_TYPES.get(ftype, "")}
        )
        entry["count"] = int(entry["count"]) + n  # type: ignore[call-overload]
        by_sev[sev] = by_sev.get(sev, 0) + n
        if ev == "observed":
            observed += n
        else:
            heuristic += n
    return {
        "total": observed + heuristic,
        "observed": observed,
        "heuristic": heuristic,
        "by_type": sorted(by_type.values(), key=lambda e: -int(e["count"])),  # type: ignore[call-overload]
        "by_severity": by_sev,
    }


@router.get("/failures/types")
def failure_types() -> dict[str, str]:
    return FAILURE_TYPES


@router.get("/clusters", response_model=Page[ClusterOut])
def list_clusters(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    job_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    q = select(Cluster)
    if job_id:
        q = q.where(Cluster.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(
        db.scalars(q.order_by(Cluster.size.desc(), Cluster.id).offset((page - 1) * page_size).limit(page_size))
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/clusters/{cluster_id}", response_model=ClusterWithExamples)
def get_cluster(
    cluster_id: str, samples: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)
) -> dict[str, object]:
    c = db.get(Cluster, cluster_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cluster not found")
    rep = db.get(Trace, c.representative_trace_id) if c.representative_trace_id else None
    sample_rows = list(
        db.scalars(select(Trace).where(Trace.cluster_id == c.id).order_by(Trace.start_time).limit(samples))
    )
    out = ClusterOut.model_validate(c).model_dump()
    out["representative"] = TraceSummary.model_validate(rep) if rep else None
    out["samples"] = [TraceSummary.model_validate(t) for t in sample_rows]
    return out
