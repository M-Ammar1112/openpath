"""API v1 router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    applications,
    health,
    opportunities,
    profile,
    sources,
    watchlists,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(opportunities.router)
api_router.include_router(profile.router)
api_router.include_router(applications.router)
api_router.include_router(watchlists.router)
api_router.include_router(sources.router)

__all__ = ["api_router"]
