"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.api.routes import datasets, ingestion, system, traces
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.database import session as db_session
from app.processing.embeddings import embedding_backend_available
from app.schemas.api import HealthOut
from app.services.datasets import ensure_builtin_categories

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    db_session.run_migrations()
    with db_session.SessionLocal() as db:
        ensure_builtin_categories(db)
    logger.info("EVALS backend ready")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="EVALS API",
        version=__version__,
        description="Automated evaluation dataset generator from production LLM logs.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Key"],
        expose_headers=["Content-Disposition", "X-Example-Count"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo submitted values back (they may contain sensitive content).
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    for router in (ingestion.router, traces.router, datasets.router, system.router):
        app.include_router(router, prefix="/api/v1")

    @app.get("/health", response_model=HealthOut, tags=["system"])
    def health() -> dict[str, object]:
        try:
            with db_session.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_state = "ok"
        except Exception:  # pragma: no cover - only when the DB is unreachable
            db_state = "unavailable"
        return {
            "status": "ok" if db_state == "ok" else "degraded",
            "version": __version__,
            "database": db_state,
            "embeddings_available": embedding_backend_available(),
            "admin_enabled": bool(settings.admin_api_key),
        }

    return app


app = create_app()
