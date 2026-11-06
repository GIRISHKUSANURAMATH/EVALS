"""Runtime-adjustable processing settings persisted in the database."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting
from app.privacy.redactor import DEFAULT_SENSITIVE_FIELDS

_KEY = "runtime"


class RuntimeSettings(BaseModel):
    latency_threshold_ms: int = Field(default=10_000, ge=100, le=600_000)
    similarity_threshold: float = Field(default=0.90, ge=0.5, le=1.0)
    semantic_dedup: bool = True
    clustering_method: str = Field(default="kmeans", pattern="^(kmeans|dbscan)$")
    max_clusters: int = Field(default=12, ge=2, le=50)
    use_embeddings: bool = False
    redact_ip_addresses: bool = True
    sensitive_fields: list[str] = Field(default_factory=lambda: sorted(DEFAULT_SENSITIVE_FIELDS))
    custom_patterns: dict[str, str] = Field(default_factory=dict)
    repeated_failure_min: int = Field(default=3, ge=2, le=100)

    @field_validator("custom_patterns")
    @classmethod
    def _check_patterns(cls, v: dict[str, str]) -> dict[str, str]:
        for name, pattern in v.items():
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name):
                raise ValueError(f"invalid pattern name: {name!r}")
            if len(pattern) > 500:
                raise ValueError(f"pattern {name!r} is too long")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"pattern {name!r} is not a valid regex: {exc}") from exc
        return v


def defaults_from_env() -> RuntimeSettings:
    s = get_settings()
    return RuntimeSettings(
        latency_threshold_ms=s.latency_threshold_ms,
        similarity_threshold=s.similarity_threshold,
        clustering_method=s.clustering_method,
        use_embeddings=s.use_embeddings,
        redact_ip_addresses=s.redact_ip_addresses,
    )


def get_runtime_settings(db: Session) -> RuntimeSettings:
    row = db.get(AppSetting, _KEY)
    base = defaults_from_env().model_dump()
    if row and isinstance(row.value, dict):
        base.update(row.value)
    return RuntimeSettings.model_validate(base)


def update_runtime_settings(db: Session, patch: dict[str, object]) -> RuntimeSettings:
    current = get_runtime_settings(db).model_dump()
    current.update({k: v for k, v in patch.items() if v is not None})
    validated = RuntimeSettings.model_validate(current)
    row = db.get(AppSetting, _KEY)
    if row is None:
        db.add(AppSetting(key=_KEY, value=validated.model_dump()))
    else:
        row.value = validated.model_dump()
    db.commit()
    return validated
