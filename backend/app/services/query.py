"""Opportunity search: filtering, sorting, and pagination.

Filters mirror the dashboard UI. All access goes through SQLAlchemy
expressions (parameterized), so no string-built SQL is possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.enums import FundingType, FreshnessStatus, OpportunityType, SortField
from app.persistence.models import Application, Opportunity, OpportunitySourceLink

SORT_OPTIONS: dict[SortField, tuple[str, bool]] = {
    # field, descending
    SortField.RELEVANCE: ("relevance_score", True),
    SortField.DEADLINE: ("deadline", False),
    SortField.NEWEST: ("discovered_at", True),
    SortField.FUNDING: ("funding_type", False),
    SortField.TUITION: ("tuition", False),
    SortField.SALARY: ("salary", True),
}


@dataclass(slots=True)
class OpportunityFilters:
    """Query parameters accepted by the API and watchlists."""

    q: str | None = None
    opportunity_type: list[OpportunityType] = field(default_factory=list)
    funding_type: list[FundingType] = field(default_factory=list)
    country: list[str] = field(default_factory=list)
    organization: str | None = None
    degree_level: str | None = None
    field_: str | None = None
    source_key: str | None = None
    remote_status: str | None = None
    deadline_after: date | None = None
    deadline_before: date | None = None
    min_score: float | None = None
    max_tuition: float | None = None
    min_salary: float | None = None
    only_saved: bool = False
    is_archived: bool = False
    freshness: list[FreshnessStatus] = field(default_factory=list)
    discovered_after: date | None = None
    verified_after: date | None = None
    application_status: str | None = None
    sort: SortField = SortField.RELEVANCE
    limit: int = 50
    offset: int = 0


def build_query(filters: OpportunityFilters) -> Select[tuple[Opportunity]]:
    stmt = select(Opportunity).where(Opportunity.is_archived.is_(filters.is_archived))

    if filters.q:
        like = f"%{filters.q.strip()}%"
        stmt = stmt.where(
            or_(
                Opportunity.title.ilike(like),
                Opportunity.description.ilike(like),
                Opportunity.organization.ilike(like),
                Opportunity.field.ilike(like),
                Opportunity.research_area.ilike(like),
            )
        )
    if filters.opportunity_type:
        stmt = stmt.where(Opportunity.opportunity_type.in_(filters.opportunity_type))
    if filters.funding_type:
        stmt = stmt.where(Opportunity.funding_type.in_(filters.funding_type))
    if filters.country:
        stmt = stmt.where(Opportunity.country.in_(filters.country))
    if filters.organization:
        stmt = stmt.where(Opportunity.organization.ilike(f"%{filters.organization}%"))
    if filters.degree_level:
        stmt = stmt.where(Opportunity.degree_level.ilike(f"%{filters.degree_level}%"))
    if filters.field_:
        stmt = stmt.where(Opportunity.field.ilike(f"%{filters.field_}%"))
    if filters.source_key:
        stmt = stmt.where(
            Opportunity.id.in_(
                select(OpportunitySourceLink.opportunity_id).where(
                    OpportunitySourceLink.source_key == filters.source_key
                )
            )
        )
    if filters.remote_status:
        stmt = stmt.where(Opportunity.remote_status == filters.remote_status)
    if filters.deadline_after:
        stmt = stmt.where(Opportunity.deadline >= filters.deadline_after)
    if filters.deadline_before:
        stmt = stmt.where(Opportunity.deadline <= filters.deadline_before)
    if filters.min_score is not None:
        stmt = stmt.where(Opportunity.relevance_score >= filters.min_score)
    if filters.max_tuition is not None:
        stmt = stmt.where(
            or_(Opportunity.tuition.is_(None), Opportunity.tuition <= filters.max_tuition)
        )
    if filters.min_salary is not None:
        stmt = stmt.where(Opportunity.salary >= filters.min_salary)
    if filters.only_saved:
        stmt = stmt.where(Opportunity.is_saved.is_(True))
    if filters.freshness:
        stmt = stmt.where(Opportunity.freshness_status.in_(filters.freshness))
    if filters.discovered_after:
        stmt = stmt.where(func.date(Opportunity.discovered_at) >= filters.discovered_after)
    if filters.verified_after:
        stmt = stmt.where(func.date(Opportunity.last_verified_at) >= filters.verified_after)
    if filters.application_status:
        stmt = stmt.where(
            Opportunity.id.in_(
                select(Application.opportunity_id).where(
                    Application.status == filters.application_status
                )
            )
        )

    column_name, descending = SORT_OPTIONS.get(filters.sort, SORT_OPTIONS[SortField.RELEVANCE])
    column = getattr(Opportunity, column_name)
    stmt = stmt.order_by(column.desc().nullslast() if descending else column.asc().nullsfirst())
    return stmt


def count_matches(session: Session, filters: OpportunityFilters) -> int:
    stmt = build_query(filters)
    subquery = stmt.with_only_columns(Opportunity.id).order_by(None).subquery()
    return int(session.execute(select(func.count()).select_from(subquery)).scalar_one())


def list_opportunities(
    session: Session, filters: OpportunityFilters
) -> tuple[list[Opportunity], int]:
    """Return (page of opportunities, total matching count)."""
    total = count_matches(session, filters)
    page = filters.limit if filters.limit > 0 else 50
    stmt = build_query(filters).limit(min(page, 200)).offset(max(0, filters.offset))
    rows = list(session.execute(stmt).scalars())
    return rows, total


def distinct_countries(session: Session) -> list[str]:
    rows = session.execute(
        select(Opportunity.country)
        .where(Opportunity.country.is_not(None), Opportunity.is_archived.is_(False))
        .distinct()
        .order_by(Opportunity.country)
    ).scalars()
    return [row for row in rows if row]


def distinct_organizations(session: Session, limit: int = 200) -> list[str]:
    rows = session.execute(
        select(Opportunity.organization)
        .where(Opportunity.organization.is_not(None), Opportunity.is_archived.is_(False))
        .distinct()
        .order_by(Opportunity.organization)
        .limit(limit)
    ).scalars()
    return [row for row in rows if row]


def get_opportunity(session: Session, opportunity_id: int) -> Opportunity | None:
    return session.get(Opportunity, opportunity_id)


__all__ = [
    "SORT_OPTIONS",
    "OpportunityFilters",
    "build_query",
    "count_matches",
    "distinct_countries",
    "distinct_organizations",
    "get_opportunity",
    "list_opportunities",
]

