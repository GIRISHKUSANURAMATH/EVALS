"""Pydantic request/response schemas for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------- ingestion
class ProcessingEventOut(ORM):
    id: int
    stage: str
    status: str
    message: str
    duration_ms: float
    details: dict[str, Any]
    created_at: datetime


class JobOut(ORM):
    id: str
    filename: str
    file_format: str
    source: str
    status: str
    file_size_bytes: int
    total_records: int
    valid_records: int
    invalid_records: int
    trace_count: int
    redaction_counts: dict[str, Any]
    stats: dict[str, Any]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class JobDetail(JobOut):
    events: list[ProcessingEventOut]


# ---------------------------------------------------------------- traces
class FailureOut(ORM):
    id: int
    trace_id: str
    job_id: str
    failure_type: str
    evidence: str
    severity: str
    detail: str
    turn_index: int | None


class TraceSummary(ORM):
    id: str
    job_id: str
    trace_key: str
    start_time: datetime | None
    turn_count: int
    total_latency_ms: float | None
    total_tokens: int | None
    models: list[str]
    status: str
    is_complete: bool
    has_missing_response: bool
    input_text: str
    output_text: str | None
    failure_types: list[str]
    duplicate_of_id: str | None
    duplicate_method: str | None
    duplicate_score: float
    duplicate_group_size: int
    cluster_id: str | None


class TraceDetail(TraceSummary):
    end_time: datetime | None
    system_prompt: str | None
    conversation: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    failures: list[FailureOut]


class FailureWithTrace(FailureOut):
    trace_key: str
    input_text: str


class FailureSummary(BaseModel):
    total: int
    observed: int
    heuristic: int
    by_type: list[dict[str, Any]]
    by_severity: dict[str, int]


# ---------------------------------------------------------------- clusters
class ClusterOut(ORM):
    id: str
    job_id: str
    label: str
    method: str
    size: int
    top_terms: list[str]
    failure_rate: float
    representative_trace_id: str | None
    created_at: datetime


class ClusterWithExamples(ClusterOut):
    representative: TraceSummary | None = None
    samples: list[TraceSummary] = []


# ---------------------------------------------------------------- datasets
class GenerateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    job_ids: list[str] | None = None
    include_successful: bool = True
    exclude_duplicates: bool = True
    categories: list[str] | None = None
    min_quality: float = Field(default=0.0, ge=0, le=1)
    max_examples: int = Field(default=5000, ge=1, le=100_000)


class DatasetVersionOut(ORM):
    id: str
    version_number: int
    example_count: int
    approved_count: int
    notes: str
    checksum: str
    created_at: datetime


class DatasetOut(ORM):
    id: str
    name: str
    description: str
    source_job_ids: list[str]
    generation_config: dict[str, Any]
    current_version: int
    created_at: datetime
    updated_at: datetime


class DatasetDetail(DatasetOut):
    stats: dict[str, Any]
    versions: list[DatasetVersionOut]


class DatasetListItem(DatasetOut):
    example_count: int
    approved_count: int


class VersionCreate(BaseModel):
    notes: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------- examples
class AnnotationOut(ORM):
    id: int
    action: str
    reviewer: str
    previous_values: dict[str, Any]
    new_values: dict[str, Any]
    note: str
    created_at: datetime


class ExampleOut(ORM):
    id: str
    dataset_id: str
    source_trace_id: str | None
    source_trace_key: str
    source_job_id: str
    source_timestamp: datetime | None
    input: str
    system_prompt: str | None
    context: list[dict[str, Any]]
    actual_output: str | None
    expected_output: str | None
    expected_output_source: str
    expected_output_rationale: str
    category: str
    failure_type: str | None
    failure_evidence: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    confidence_score: float
    quality_score: float
    quality_factors: list[dict[str, Any]]
    review_status: str
    reviewer_notes: str
    created_at: datetime
    updated_at: datetime


class ExampleDetail(ExampleOut):
    annotations: list[AnnotationOut]


class ExamplePatch(BaseModel):
    expected_output: str | None = Field(default=None, max_length=50_000)
    category: str | None = Field(default=None, max_length=64)
    reviewer_notes: str | None = Field(default=None, max_length=5000)
    reviewer: str = Field(default="reviewer", min_length=1, max_length=128)


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "flag", "reset"]
    reviewer: str = Field(default="reviewer", min_length=1, max_length=128)
    note: str = Field(default="", max_length=5000)
    expected_output: str | None = Field(default=None, max_length=50_000)
    category: str | None = Field(default=None, max_length=64)


class BulkReviewRequest(BaseModel):
    example_ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["approve", "reject", "flag", "reset"]
    reviewer: str = Field(default="reviewer", min_length=1, max_length=128)
    note: str = Field(default="", max_length=5000)


# ---------------------------------------------------------------- categories / settings
class CategoryOut(ORM):
    id: int
    name: str
    description: str
    is_builtin: bool


class CategoryCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(default="", max_length=500)


class SettingsPatch(BaseModel):
    latency_threshold_ms: int | None = None
    similarity_threshold: float | None = None
    semantic_dedup: bool | None = None
    clustering_method: str | None = None
    max_clusters: int | None = None
    use_embeddings: bool | None = None
    redact_ip_addresses: bool | None = None
    sensitive_fields: list[str] | None = None
    custom_patterns: dict[str, str] | None = None
    repeated_failure_min: int | None = None


class RedactionPreviewRequest(BaseModel):
    text: str = Field(max_length=20_000)


class RedactionPreviewResponse(BaseModel):
    redacted: str
    counts: dict[str, int]


class HealthOut(BaseModel):
    status: str
    version: str
    database: str
    embeddings_available: bool
    admin_enabled: bool
