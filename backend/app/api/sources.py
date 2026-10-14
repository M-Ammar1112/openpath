"""Source management, refresh triggers, and analytics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.persistence.models import Source, SourceFetch
from app.schemas.source import (
    RefreshSummary,
    SourceFetchRead,
    SourceRead,
    SourceRunResultRead,
    SourceUpdate,
)
from app.services import analytics as analytics_service
from app.services.ingest import run_all_sources, run_source

router = APIRouter(tags=["sources"])


@router.get("/sources", response_model=list[SourceRead], summary="List configured sources")
def list_sources(session: DbSession) -> list[SourceRead]:
    rows = session.execute(select(Source).order_by(Source.id)).scalars()
    return [SourceRead.model_validate(row) for row in rows]


@router.patch("/sources/{source_id}", response_model=SourceRead, summary="Update a source")
def update_source(source_id: int, payload: SourceUpdate, session: DbSession) -> SourceRead:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(source, key, value)
    session.flush()
    return SourceRead.model_validate(source)


@router.get(
    "/sources/{source_id}/history",
    response_model=list[SourceFetchRead],
    summary="Fetch history for a source",
)
def source_history(
    source_id: int, session: DbSession, limit: int = Query(default=20, ge=1, le=200)
) -> list[SourceFetchRead]:
    if session.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail="source not found")
    rows = session.execute(
        select(SourceFetch)
        .where(SourceFetch.source_id == source_id)
        .order_by(SourceFetch.started_at.desc())
        .limit(limit)
    ).scalars()
    return [SourceFetchRead.model_validate(row) for row in rows]


@router.post(
    "/sources/{source_id}/refresh",
    response_model=SourceRunResultRead,
    summary="Refresh a single source now",
)
async def refresh_source(source_id: int, session: DbSession) -> SourceRunResultRead:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    result = await run_source(session, source)
    session.commit()
    return SourceRunResultRead.model_validate(result.as_dict())


@router.post(
    "/sources/refresh-all", response_model=RefreshSummary, summary="Refresh every enabled source"
)
async def refresh_all(session: DbSession) -> RefreshSummary:
    results = await run_all_sources(session)
    return RefreshSummary(
        sources=[SourceRunResultRead.model_validate(r.as_dict()) for r in results],
        total_new=sum(r.new for r in results),
        total_updated=sum(r.updated for r in results),
        errors=sum(1 for r in results if r.status == "error"),
    )


@router.get("/analytics/dashboard", summary="Dashboard analytics summary")
def dashboard(session: DbSession) -> dict[str, object]:
    return analytics_service.dashboard_summary(session)


@router.get("/analytics/deadlines", summary="Upcoming deadlines by month")
def deadlines(session: DbSession, months: int = Query(default=6, ge=1, le=24)) -> dict[str, object]:
    return {"deadlines_by_month": analytics_service.deadline_calendar(session, months=months)}


@router.get("/analytics/applications", summary="Application funnel metrics")
def applications(session: DbSession) -> dict[str, object]:
    return analytics_service.applications_summary(session)


__all__ = ["router"]
