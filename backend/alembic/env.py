"""Alembic environment. The URL is injected by app.database.session.run_migrations()
or taken from EVALS_DATABASE_URL when running the alembic CLI directly."""

from __future__ import annotations

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (registers models on Base.metadata)
from alembic import context
from app.core.config import get_settings
from app.database.session import Base, set_alembic_url

config = context.config
if config.get_main_option("sqlalchemy.url") in (None, "", "sqlite:///data/evals.db"):
    set_alembic_url(config, get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
