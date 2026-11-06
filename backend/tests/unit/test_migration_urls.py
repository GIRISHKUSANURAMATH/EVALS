"""Regression tests: database URLs containing '%' must survive Alembic's ConfigParser.

SQLAlchemy's URL.render_as_string() percent-encodes special characters in the SQLite path
(':' -> '%3A', '%' -> '%25'), so on Windows a path like C:/Users/... becomes C%3A/Users/...
Alembic stores options in a ConfigParser, where an unescaped '%' raises
"ValueError: invalid interpolation syntax".
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.database import session as db_session

WINDOWS_URL = "sqlite:///C:/Users/Girish K/AppData/Local/Temp/evals-test-abc/evals.db"


def test_rendered_windows_url_is_percent_encoded() -> None:
    # Documents the trigger: SQLAlchemy encodes the drive-letter colon.
    rendered = make_url(WINDOWS_URL).render_as_string(hide_password=False)
    assert "C%3A/Users/Girish K/" in rendered


def test_windows_url_round_trips_through_alembic_config() -> None:
    rendered = make_url(WINDOWS_URL).render_as_string(hide_password=False)
    cfg = Config()
    db_session.set_alembic_url(cfg, rendered)
    stored = cfg.get_main_option("sqlalchemy.url")
    assert stored == rendered
    # The value Alembic hands to SQLAlchemy still resolves to the original Windows path.
    assert make_url(stored).database == "C:/Users/Girish K/AppData/Local/Temp/evals-test-abc/evals.db"


def test_unescaped_percent_is_what_breaks_configparser() -> None:
    rendered = make_url(WINDOWS_URL).render_as_string(hide_password=False)
    with pytest.raises(ValueError, match="interpolation"):
        Config().set_main_option("sqlalchemy.url", rendered)


def _assert_migrated(db_file: Path) -> None:
    assert db_file.exists()
    with sqlite3.connect(db_file) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"alembic_version", "ingestion_jobs", "traces", "eval_examples"} <= tables


def test_migrations_run_on_path_with_spaces_and_percent(tmp_path: Path) -> None:
    # Valid on Windows and Linux: spaces and a literal '%' (rendered by SQLAlchemy as %25).
    db_file = tmp_path / "Users" / "Girish K" / "100% data" / "evals.db"
    url = f"sqlite:///{db_file.as_posix()}"
    assert "%25" in make_url(url).render_as_string(hide_password=False)

    db_session.configure_engine(url)
    try:
        db_session.run_migrations()  # no explicit URL: uses the rendered engine URL, as app startup does
    finally:
        db_session.engine.dispose()
    _assert_migrated(db_file)


@pytest.mark.skipif(sys.platform == "win32", reason="'C:' is only a legal directory name on POSIX")
def test_migrations_run_on_drive_letter_style_path(tmp_path: Path) -> None:
    # Reproduces the exact Windows failure (C: -> C%3A) on Linux/macOS CI runners.
    db_file = tmp_path / "C:" / "Users" / "Girish K" / "AppData" / "Local" / "Temp" / "evals.db"
    url = f"sqlite:///{db_file.as_posix()}"
    assert "C%3A" in make_url(url).render_as_string(hide_password=False)

    db_session.configure_engine(url)
    try:
        db_session.run_migrations()
    finally:
        db_session.engine.dispose()
    _assert_migrated(db_file)
