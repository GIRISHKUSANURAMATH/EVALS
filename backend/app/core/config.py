"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime settings. Every value can be overridden with an EVALS_* env var."""

    model_config = SettingsConfigDict(
        env_prefix="EVALS_",
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "EVALS"
    environment: str = "development"
    database_url: str = Field(
        default=f"sqlite:///{(BACKEND_DIR / 'data' / 'evals.db').as_posix()}",
        description="SQLAlchemy URL. SQLite by default; PostgreSQL-compatible schema.",
    )
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Upload limits
    max_upload_mb: int = 25
    max_records_per_upload: int = 200_000

    # Sensitive operations (database reset) are disabled unless this key is set.
    admin_api_key: str = ""

    # Privacy
    preserve_raw_content: bool = False
    redact_ip_addresses: bool = True

    # Pipeline defaults
    latency_threshold_ms: int = 10_000
    similarity_threshold: float = 0.9
    clustering_method: str = "kmeans"
    use_embeddings: bool = False
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Optional LLM assistance: "none" (default) or "openai_compatible".
    llm_provider: str = "none"

    sample_data_dir: Path = PROJECT_DIR / "sample_data"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
