"""SQLAlchemy ORM models.

Schema is written to be PostgreSQL-compatible: only portable column types are used
(String, Text, Integer, Float, Boolean, DateTime, JSON).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="upload")  # upload | sample
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    valid_records: Mapped[int] = mapped_column(Integer, default=0)
    invalid_records: Mapped[int] = mapped_column(Integer, default=0)
    trace_count: Mapped[int] = mapped_column(Integer, default=0)
    redaction_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    records: Mapped[list[LogRecord]] = relationship(back_populates="job", cascade="all, delete-orphan")
    traces: Mapped[list[Trace]] = relationship(back_populates="job", cascade="all, delete-orphan")
    events: Mapped[list[ProcessingEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ProcessingEvent.id"
    )
    clusters: Mapped[list[Cluster]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Trace(Base):
    __tablename__ = "traces"
    __table_args__ = (
        UniqueConstraint("job_id", "trace_key", name="uq_trace_job_key"),
        Index("ix_traces_job_status", "job_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True)
    trace_key: Mapped[str] = mapped_column(String(255), index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="ok")  # ok | failed | warning
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    has_missing_response: Mapped[bool] = mapped_column(Boolean, default=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    failure_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    normalized_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    duplicate_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duplicate_score: Mapped[float] = mapped_column(Float, default=0.0)
    duplicate_group_size: Mapped[int] = mapped_column(Integer, default=1)
    cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )

    job: Mapped[IngestionJob] = relationship(back_populates="traces")
    failures: Mapped[list[Failure]] = relationship(back_populates="trace", cascade="all, delete-orphan")
    cluster: Mapped[Cluster | None] = relationship(back_populates="traces", foreign_keys=[cluster_id])


class LogRecord(Base):
    __tablename__ = "log_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True)
    trace_id: Mapped[str | None] = mapped_column(
        ForeignKey("traces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer)
    trace_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    assistant_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    redaction_count: Mapped[int] = mapped_column(Integer, default=0)
    # Only populated when EVALS_PRESERVE_RAW_CONTENT=true. Never exported, never returned by the API.
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[IngestionJob] = relationship(back_populates="records")


class Failure(Base):
    __tablename__ = "failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    failure_type: Mapped[str] = mapped_column(String(64), index=True)
    evidence: Mapped[str] = mapped_column(String(16))  # observed | heuristic
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    detail: Mapped[str] = mapped_column(Text, default="")
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    trace: Mapped[Trace] = relationship(back_populates="failures")


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(255))
    method: Mapped[str] = mapped_column(String(32))
    size: Mapped[int] = mapped_column(Integer, default=0)
    top_terms: Mapped[list[str]] = mapped_column(JSON, default=list)
    failure_rate: Mapped[float] = mapped_column(Float, default=0.0)
    representative_trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[IngestionJob] = relationship(back_populates="clusters")
    traces: Mapped[list[Trace]] = relationship(back_populates="cluster", foreign_keys="Trace.cluster_id")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    source_job_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    generation_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    examples: Mapped[list[EvalExample]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetVersion.version_number"
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    example_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="versions")


class EvalExample(Base):
    __tablename__ = "eval_examples"
    __table_args__ = (
        Index("ix_examples_dataset_status", "dataset_id", "review_status"),
        Index("ix_examples_dataset_category", "dataset_id", "category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    source_trace_id: Mapped[str | None] = mapped_column(
        ForeignKey("traces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_trace_key: Mapped[str] = mapped_column(String(255), default="")
    source_job_id: Mapped[str] = mapped_column(String(36), default="")
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    input: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    actual_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    # none | candidate | human_approved
    expected_output_source: Mapped[str] = mapped_column(String(32), default="none")
    expected_output_rationale: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), index=True)
    failure_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_evidence: Mapped[str] = mapped_column(String(16), default="none")  # observed | heuristic | none
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reviewer_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="examples")
    annotations: Mapped[list[ReviewAnnotation]] = relationship(
        back_populates="example", cascade="all, delete-orphan", order_by="ReviewAnnotation.id"
    )


class ReviewAnnotation(Base):
    __tablename__ = "review_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    example_id: Mapped[str] = mapped_column(ForeignKey("eval_examples.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    reviewer: Mapped[str] = mapped_column(String(128), default="anonymous")
    previous_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    new_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    example: Mapped[EvalExample] = relationship(back_populates="annotations")


class ProcessingEvent(Base):
    __tablename__ = "processing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # completed | failed | skipped
    message: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[IngestionJob] = relationship(back_populates="events")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
