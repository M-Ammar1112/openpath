"""Opportunity endpoints: search, detail, user edits, manual creation."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.connectors.base import NormalizedOpportunity
from app.enums import (
    FundingType,
    FreshnessStatus,
    OpportunityType,
    SortField,
    SourceCategory,
)
from app.persistence.models import Opportunity, Source
from app.schemas.opportunity import (
    OpportunityCreate,
    OpportunityDetail,
    OpportunityListItem,
    OpportunityPage,
    OpportunityUpdate,
)
from app.services import applications as applications_service
from app.services import query as query_service
from app.services.dedup import upsert_opportunity
from app.services.scoring import build_strategy, get_profile, score_opportunity

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

MANUAL_SOURCE_KEY = "manual-curated"


@router.get("", response_model=OpportunityPage, summary="Search opportunities")
def list_opportunities(
    session: DbSession,
    q: str | None = Query(default=None, max_length=200),
    opportunity_type: list[OpportunityType] = Query(default=[]),
    funding_type: list[FundingType] = Query(default=[]),
    country: list[str] = Query(default=[]),
    organization: str | None = Query(default=None, max_length=200),
    degree_level: str | None = Query(default=None, max_length=60),
    field: str | None = Query(default=None, max_length=200),
    source_key: str | None = Query(default=None, max_length=80),
    remote_status: str | None = Query(default=None, max_length=20),
    deadline_after: date | None = None,
    deadline_before: date | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    max_tuition: float | None = Query(default=None, ge=0),
    min_salary: float | None = Query(default=None, ge=0),
    only_saved: bool = False,
    is_archived: bool = False,
    freshness: list[FreshnessStatus] = Query(default=[]),
    discovered_after: date | None = None,
    verified_after: date | None = None,
    application_status: str | None = Query(default=None, max_length=30),
    sort: SortField = SortField.RELEVANCE,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> OpportunityPage:
    """Search with dashboard filters. All filters are optional and combined with AND."""
    filters = query_service.OpportunityFilters(
        q=q,
        opportunity_type=list(opportunity_type),
        funding_type=list(funding_type),
        country=list(country),
        organization=organization,
        degree_level=degree_level,
        field_=field,
        source_key=source_key,
        remote_status=remote_status,
        deadline_after=deadline_after,
        deadline_before=deadline_before,
        min_score=min_score,
        max_tuition=max_tuition,
        min_salary=min_salary,
        only_saved=only_saved,
        is_archived=is_archived,
        freshness=list(freshness),
        discovered_after=discovered_after,
        verified_after=verified_after,
        application_status=application_status,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    rows, total = query_service.list_opportunities(session, filters)
    return OpportunityPage(
        items=[OpportunityListItem.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/facets", summary="Distinct countries/organizations for filter menus")
def facets(session: DbSession) -> dict[str, list[str]]:
    return {
        "countries": query_service.distinct_countries(session),
        "organizations": query_service.distinct_organizations(session),
    }


@router.get("/{opportunity_id}", response_model=OpportunityDetail, summary="Opportunity detail")
def get_opportunity(opportunity_id: int, session: DbSession) -> OpportunityDetail:
    row = query_service.get_opportunity(session, opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    return OpportunityDetail.model_validate(row)


@router.patch("/{opportunity_id}", response_model=OpportunityDetail, summary="Update user fields")
def update_opportunity(
    opportunity_id: int,
    payload: OpportunityUpdate,
    session: DbSession,
) -> OpportunityDetail:
    """Only user-owned fields can change here; source facts stay read-only."""
    row = query_service.get_opportunity(session, opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    data = payload.model_dump(exclude_unset=True)
    if "notes" in data:
        row.notes = data["notes"]
    if data.get("is_archived") is not None:
        row.is_archived = bool(data["is_archived"])
    if data.get("is_saved") is not None:
        applications_service.toggle_saved(session, row, saved=bool(data["is_saved"]))
    session.flush()
    return OpportunityDetail.model_validate(row)


@router.post(
    "/{opportunity_id}/save", response_model=OpportunityDetail, summary="Toggle saved/favourite"
)
def toggle_save(opportunity_id: int, session: DbSession) -> OpportunityDetail:
    row = query_service.get_opportunity(session, opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    applications_service.toggle_saved(session, row)
    session.flush()
    return OpportunityDetail.model_validate(row)


@router.post(
    "",
    response_model=OpportunityDetail,
    status_code=201,
    summary="Create an opportunity manually",
)
def create_opportunity(
    payload: OpportunityCreate, session: DbSession
) -> OpportunityDetail:
    """Manual entry — deduplicated and validated exactly like collector output."""
    source = session.execute(select(Source).where(Source.key == MANUAL_SOURCE_KEY)).scalar_one_or_none()
    if source is None:
        source = Source(
            key=MANUAL_SOURCE_KEY,
            name="Manually curated opportunities",
            category=SourceCategory.MANUAL,
            connector_type="manual",
            enabled=True,
        )
        session.add(source)
        session.flush()
    candidate = NormalizedOpportunity(
        title=payload.title,
        official_url=payload.official_url,
        organization=payload.organization,
        country=payload.country,
        city=payload.city,
        opportunity_type=payload.opportunity_type,
        funding_type=payload.funding_type,
        funding_type_raw=payload.funding_type_raw,
        deadline=payload.deadline,
        description=payload.description,
        field=payload.field,
        degree_level=payload.degree_level,
        skills=payload.skills,
        tags=payload.tags,
        raw_payload=payload.raw_payload or {"origin": "manual-entry"},
        source_key=source.key,
        source_name=source.name,
    )
    outcome = upsert_opportunity(session, candidate, source=source)
    row: Opportunity = outcome.opportunity
    score_opportunity(row, get_profile(session), build_strategy(session))
    session.flush()
    return OpportunityDetail.model_validate(row)


__all__ = ["router"]

