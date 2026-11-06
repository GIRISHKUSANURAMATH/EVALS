from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import require_admin
from app.database.session import get_db
from app.evaluation.exporters import ExportValidationError
from app.evaluation.generator import GenerationConfig
from app.models import Dataset, EvalExample
from app.schemas.api import (
    BulkReviewRequest,
    DatasetDetail,
    DatasetListItem,
    DatasetVersionOut,
    ExampleDetail,
    ExampleOut,
    ExamplePatch,
    GenerateRequest,
    Page,
    ReviewRequest,
    VersionCreate,
)
from app.services import datasets as svc

router = APIRouter(tags=["datasets"])

_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.NotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, svc.ConflictError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


@router.get("/datasets", response_model=Page[DatasetListItem])
def list_datasets(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)
) -> dict[str, object]:
    total = db.scalar(select(func.count(Dataset.id))) or 0
    counts = (
        select(
            EvalExample.dataset_id,
            func.count().label("n"),
            func.sum(case((EvalExample.review_status == "approved", 1), else_=0)).label("approved"),
        )
        .group_by(EvalExample.dataset_id)
        .subquery()
    )
    rows = db.execute(
        select(Dataset, counts.c.n, counts.c.approved)
        .outerjoin(counts, counts.c.dataset_id == Dataset.id)
        .order_by(Dataset.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for ds, n, approved in rows:
        item = DatasetListItem.model_validate(
            {
                **{
                    k: getattr(ds, k)
                    for k in DatasetListItem.model_fields
                    if k not in ("example_count", "approved_count")
                },
                "example_count": n or 0,
                "approved_count": int(approved or 0),
            }
        )
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/datasets/generate", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED)
def generate(req: GenerateRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    cfg = GenerationConfig(
        include_successful=req.include_successful,
        exclude_duplicates=req.exclude_duplicates,
        categories=req.categories,
        min_quality=req.min_quality,
        max_examples=req.max_examples,
    )
    try:
        ds = svc.generate_dataset(db, req.name, req.description, req.job_ids, cfg)
    except (svc.ConflictError, svc.NotFoundError) as exc:
        raise _handle(exc) from exc
    return _detail(db, ds.id)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    return _detail(db, dataset_id)


def _detail(db: Session, dataset_id: str) -> dict[str, object]:
    ds = db.scalar(select(Dataset).options(selectinload(Dataset.versions)).where(Dataset.id == dataset_id))
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    base = {
        k: getattr(ds, k)
        for k in (
            "id",
            "name",
            "description",
            "source_job_ids",
            "generation_config",
            "current_version",
            "created_at",
            "updated_at",
        )
    }
    return base | {
        "stats": svc.dataset_stats(db, ds.id),
        "versions": [DatasetVersionOut.model_validate(v) for v in ds.versions],
    }


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_dataset(dataset_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        svc.delete_dataset(db, dataset_id)
    except svc.NotFoundError as exc:
        raise _handle(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/datasets/{dataset_id}/versions", response_model=DatasetVersionOut, status_code=status.HTTP_201_CREATED)
def create_version(dataset_id: str, req: VersionCreate, db: Session = Depends(get_db)) -> object:
    try:
        return svc.create_version(db, dataset_id, req.notes)
    except svc.NotFoundError as exc:
        raise _handle(exc) from exc


@router.get("/datasets/{dataset_id}/examples", response_model=Page[ExampleOut])
def list_examples(
    dataset_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status", pattern="^(pending|approved|rejected|flagged)$"),
    category: str | None = None,
    failure_type: str | None = None,
    search: str | None = Query(None, max_length=200),
    sort: str = Query("quality_desc", pattern="^(quality_desc|quality_asc|newest|oldest)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if db.get(Dataset, dataset_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    items, total = svc.query_examples(
        db, dataset_id, status_filter, category, search, failure_type, page, page_size, sort
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/examples/{example_id}", response_model=ExampleDetail)
def get_example(example_id: str, db: Session = Depends(get_db)) -> object:
    ex = db.scalar(
        select(EvalExample).options(selectinload(EvalExample.annotations)).where(EvalExample.id == example_id)
    )
    if ex is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Example not found")
    return ex


@router.patch("/examples/{example_id}", response_model=ExampleOut)
def patch_example(example_id: str, req: ExamplePatch, db: Session = Depends(get_db)) -> object:
    try:
        return svc.update_example(
            db, example_id, req.model_dump(exclude={"reviewer"}, exclude_unset=True), req.reviewer
        )
    except (svc.NotFoundError, svc.ConflictError) as exc:
        raise _handle(exc) from exc


@router.post("/examples/{example_id}/review", response_model=ExampleOut)
def review_example(example_id: str, req: ReviewRequest, db: Session = Depends(get_db)) -> object:
    try:
        return svc.review_example(db, example_id, req.action, req.reviewer, req.note, req.expected_output, req.category)
    except (svc.NotFoundError, svc.ConflictError) as exc:
        raise _handle(exc) from exc


@router.post("/examples/bulk-review")
def bulk_review(req: BulkReviewRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    done, missing = [], []
    for eid in req.example_ids:
        try:
            svc.review_example(db, eid, req.action, req.reviewer, req.note)
            done.append(eid)
        except svc.NotFoundError:
            missing.append(eid)
    return {"updated": len(done), "not_found": missing}


@router.get("/exports/{dataset_id}")
def export(
    dataset_id: str,
    format: Literal["jsonl", "csv", "json"] = "jsonl",
    approved_only: bool = False,
    categories: str | None = Query(None, max_length=1000, description="Comma-separated category names"),
    statuses: str | None = Query(None, max_length=200, description="Comma-separated review statuses"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
) -> Response:
    if not re.match(_UUID, dataset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid dataset id")
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    sts = [s.strip() for s in statuses.split(",") if s.strip()] if statuses else None
    if sts and not set(sts) <= {"pending", "approved", "rejected", "flagged"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid review status filter")
    try:
        body, count, _manifest = svc.export_dataset(
            db, dataset_id, format, approved_only, cats, date_from, date_to, sts
        )
    except svc.NotFoundError as exc:
        raise _handle(exc) from exc
    except ExportValidationError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Export validation failed: {exc}") from exc
    media = {"jsonl": "application/x-ndjson", "csv": "text/csv", "json": "application/json"}[format]
    filename = f"evals_{dataset_id[:8]}_{'approved' if approved_only else 'all'}.{format}"
    return Response(
        content=body,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Example-Count": str(count)},
    )
