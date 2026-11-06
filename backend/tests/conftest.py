from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="evals-test-"))
os.environ["EVALS_DATABASE_URL"] = f"sqlite:///{(_TMP / 'bootstrap.db').as_posix()}"
os.environ.setdefault("EVALS_ADMIN_API_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database import session as db_session  # noqa: E402
from app.main import app  # noqa: E402

ADMIN_KEY = "test-admin-key"
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'evals.db').as_posix()}"


@pytest.fixture()
def client(db_url: str) -> Iterator[TestClient]:
    db_session.configure_engine(db_url)
    with TestClient(app) as c:
        yield c
    db_session.engine.dispose()


@pytest.fixture()
def db(client: TestClient) -> Iterator[object]:
    s = db_session.SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def admin_enabled(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "admin_api_key", ADMIN_KEY)
    return ADMIN_KEY


@pytest.fixture()
def loaded(client: TestClient) -> dict[str, object]:
    r = client.post("/api/v1/ingestion/sample?name=production_logs")
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def dataset(client: TestClient, loaded: dict[str, object]) -> dict[str, object]:
    r = client.post("/api/v1/datasets/generate", json={"name": "test dataset"})
    assert r.status_code == 201, r.text
    return r.json()
