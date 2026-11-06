from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.security import sanitize_filename
from app.database.session import get_db
from app.ingestion.validation import UploadValidationError
from app.models import IngestionJob
from app.schemas.api import JobDetail, JobOut, Page
from app.services.pipeline import process_upload

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

SAMPLE_FILES = {
    "production_logs": "production_logs.jsonl",
    "openai_chat_logs": "openai_chat_logs.json",
    "support_bot_logs": "support_bot_logs.csv",
    "app_server": "app_server.log",
}


@router.post("/upload", response_model=JobDetail, status_code=status.HTTP_201_CREATED)
async def upload_logs(file: UploadFile = File(...), db: Session = Depends(get_db)) -> IngestionJob:
    """Upload a JSONL, JSON, CSV or key=value .log file and run the processing pipeline."""
    limit = get_settings().max_upload_bytes
    content = await file.read(limit + 1)
    name = sanitize_filename(file.filename)
    if len(content) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {limit // (1024 * 1024)} MB limit.")
    try:
        job = process_upload(db, name, content)
    except UploadValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _load_job(db, job.id)


@router.post("/sample", response_model=JobDetail, status_code=status.HTTP_201_CREATED)
def load_sample(
    name: str = Query(default="production_logs", description=f"One of: {', '.join(SAMPLE_FILES)}"),
    db: Session = Depends(get_db),
) -> IngestionJob:
    """Load one of the bundled synthetic sample datasets."""
    if name not in SAMPLE_FILES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown sample. Choose from: {', '.join(SAMPLE_FILES)}")
    path = get_settings().sample_data_dir / SAMPLE_FILES[name]
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample file missing. Run scripts/generate_sample_data.py.")
    try:
        job = process_upload(db, path.name, path.read_bytes(), source="sample")
    except UploadValidationError as exc:  # pragma: no cover - bundled samples are valid
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _load_job(db, job.id)


@router.get("/samples")
def list_samples() -> list[dict[str, str | bool]]:
    base = get_settings().sample_data_dir
    return [{"name": k, "filename": v, "available": (base / v).is_file()} for k, v in SAMPLE_FILES.items()]


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    q = select(IngestionJob)
    if status_filter:
        q = q.where(IngestionJob.status == status_filter)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(IngestionJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)) -> IngestionJob:
    return _load_job(db, job_id)


def _load_job(db: Session, job_id: str) -> IngestionJob:
    job = db.scalar(select(IngestionJob).options(selectinload(IngestionJob.events)).where(IngestionJob.id == job_id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job
