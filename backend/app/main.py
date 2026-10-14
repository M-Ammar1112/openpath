"""FastAPI application: wiring, lifespan, static frontend, error handling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import REPO_ROOT, settings
from app.core.http import get_http_client, reset_http_client
from app.core.urls import InvalidURLError
from app.jobs.scheduler import shutdown_scheduler, start_scheduler
from app.logging_config import configure_logging, get_logger
from app.persistence.db import get_engine, get_session_factory
from app.persistence.models import Base
from app.services.ingest import run_all_sources
from app.services.seed import seed_all

log = get_logger("openpath.main")

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def ensure_schema() -> None:
    """Create tables when migrations have not been run (local convenience).

    Alembic is the source of truth for schema changes; this keeps a fresh
    clone usable even before `alembic upgrade head`.
    """
    Base.metadata.create_all(bind=get_engine())


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.openpath_log_level, as_json=settings.is_production)
    ensure_schema()
    with get_session_factory()() as session:
        summary = seed_all(session)
        session.commit()
    log.info("startup_complete", extra={"seed": summary, "environment": settings.openpath_env})
    if settings.scheduler_enabled:
        start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        reset_http_client()
        log.info("shutdown_complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenPath",
        description="Scholarships, Universities & Career Opportunity Intelligence Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.exception_handler(InvalidURLError)  # type: ignore[misc]
    async def _invalid_url(_: Request, exc: InvalidURLError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": "OpenPath API",
            "docs": "/docs",
            "health": "/api/v1/health",
            "frontend": str(FRONTEND_DIST) if FRONTEND_DIST.exists() else "dev server (vite)",
        }

    @app.post("/api/v1/refresh", tags=["system"], summary="Refresh all sources synchronously")
    async def refresh_now() -> dict[str, object]:
        """Convenience endpoint for scripts/dev; the scheduler does this periodically."""
        with get_session_factory()() as session:
            results = await run_all_sources(session)
        return {
            "sources": [r.as_dict() for r in results],
            "total_new": sum(r.new for r in results),
            "errors": sum(1 for r in results if r.status == "error"),
        }

    # Serve the built frontend when present (production/local preview).
    if FRONTEND_DIST.exists():
        app.mount("/app", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
        log.info("frontend_mounted", extra={"path": str(FRONTEND_DIST)})

    @app.middleware("http")
    async def _identify_crawler(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Add a stable header so API use is traceable in logs."""
        response = await call_next(request)
        response.headers["X-OpenPath-Client"] = get_http_client().user_agent
        return response

    return app


app = create_app()

__all__ = ["app", "create_app", "ensure_schema"]
