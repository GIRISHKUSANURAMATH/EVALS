"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import BACKEND_DIR, get_settings

if TYPE_CHECKING:
    from alembic.config import Config


class Base(DeclarativeBase):
    pass


def _make_engine(url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        db_path = url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args, future=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


engine: Engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure_engine(url: str) -> None:
    """Re-point the global engine (used by tests and scripts)."""
    global engine
    engine.dispose()
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_alembic_url(cfg: Config, url: str) -> None:
    """Store a database URL in an Alembic Config.

    Alembic options live in a ConfigParser, where '%' starts an interpolation. Rendered
    SQLAlchemy URLs contain percent-encoding (e.g. Windows ``C:`` becomes ``C%3A``), so
    every '%' is escaped as '%%'; ``get_main_option`` returns the original URL unchanged.
    """
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


def run_migrations(url: str | None = None) -> None:
    """Apply Alembic migrations up to head."""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    set_alembic_url(cfg, url or str(engine.url.render_as_string(hide_password=False)))
    command.upgrade(cfg, "head")
