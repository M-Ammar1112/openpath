"""Dashboard analytics: useful aggregations, not decoration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ApplicationStatus, FreshnessStatus
from app.persistence.models import Application, Opportunity, OpportunitySourceLink

# Applications that count as "the employer responded".
RESPONSE_STATUSES = {
    ApplicationStatus.INTERVIEW.value,
    ApplicationStatus.OFFER.value,
    ApplicationStatus.REJECTED.value,
    ApplicationStatus.ACCEPTED.value,
}
SUBMITTED_STATUSES = {
    ApplicationStatus.APPLIED.value,
    ApplicationStatus.INTERVIEW.value,
    ApplicationStatus.OFFER.value,
    ApplicationStatus.REJECTED.value,
    ApplicationStatus.ACCEPTED.value,
}


def _grouped_counts(
    session: Session, column: Any, *, limit: int | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(column, func.count(Opportunity.id))
        .where(Opportunity.is_archived.is_(False))
        .group_by(column)
        .order_by(func.count(Opportunity.id).desc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return [
        {"value": (value.value if hasattr(value, "value") else value), "count": int(count)}
        for value, count in session.execute(stmt).all()
        if value is not None
    ]


def deadline_calendar(session: Session, *, months: int = 6) -> list[dict[str, Any]]:
    """Upcoming deadlines grouped by month (YYYY-MM)."""
    today = date.today()
    horizon = today + timedelta(days=31 * months)
    rows = session.execute(
        select(Opportunity.deadline).where(
            Opportunity.deadline.is_not(None),
            Opportunity.deadline >= today,
            Opportunity.deadline <= horizon,
            Opportunity.is_archived.is_(False),
        )
    ).scalars()
    buckets: dict[str, int] = {}
    for value in rows:
        key = value.strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0) + 1
    return [{"month": month, "count": count} for month, count in sorted(buckets.items())]


def top_organizations(session: Session, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            Opportunity.organization,
            func.count(Opportunity.id),
            func.avg(Opportunity.relevance_score),
        )
        .where(Opportunity.organization.is_not(None), Opportunity.is_archived.is_(False))
        .group_by(Opportunity.organization)
        .order_by(func.avg(Opportunity.relevance_score).desc())
        .limit(limit)
    ).all()
    return [
        {
            "organization": organization,
            "count": int(count),
            "average_score": round(float(avg_score or 0.0), 1),
        }
        for organization, count, avg_score in rows
    ]


def applications_summary(session: Session) -> dict[str, Any]:
    by_status = {
        status.value: 0 for status in ApplicationStatus
    }
    for status, count in session.execute(
        select(Application.status, func.count(Application.id)).group_by(Application.status)
    ).all():
        by_status[status.value if hasattr(status, "value") else str(status)] = int(count)
    submitted = sum(by_status.get(status, 0) for status in SUBMITTED_STATUSES)
    responded = sum(by_status.get(status, 0) for status in RESPONSE_STATUSES)
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "submitted": submitted,
        "responded": responded,
        "response_rate": round(responded / submitted, 3) if submitted else 0.0,
    }


def dashboard_summary(session: Session) -> dict[str, Any]:
    """Everything the dashboard needs in one round trip."""
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    base = select(func.count(Opportunity.id)).where(Opportunity.is_archived.is_(False))
    totals = {
        "opportunities": int(session.execute(base).scalar_one()),
        "saved": int(
            session.execute(base.where(Opportunity.is_saved.is_(True))).scalar_one()
        ),
        "new_this_week": int(
            session.execute(base.where(Opportunity.discovered_at >= week_ago)).scalar_one()
        ),
        "expired": int(
            session.execute(
                base.where(Opportunity.freshness_status == FreshnessStatus.EXPIRED)
            ).scalar_one()
        ),
        "fully_funded": int(
            session.execute(
                base.where(Opportunity.funding_type.in_(["full", "paid"]))
            ).scalar_one()
        ),
        "sources_with_data": int(
            session.execute(
                select(func.count(func.distinct(OpportunitySourceLink.source_key)))
            ).scalar_one()
        ),
    }
    return {
        "totals": totals,
        "by_type": _grouped_counts(session, Opportunity.opportunity_type),
        "by_funding": _grouped_counts(session, Opportunity.funding_type),
        "by_country": _grouped_counts(session, Opportunity.country, limit=12),
        "by_source": _source_counts(session),
        "deadlines_by_month": deadline_calendar(session),
        "top_organizations": top_organizations(session),
        "applications": applications_summary(session),
    }


def _source_counts(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(OpportunitySourceLink.source_key, func.count(OpportunitySourceLink.id))
        .group_by(OpportunitySourceLink.source_key)
        .order_by(func.count(OpportunitySourceLink.id).desc())
    ).all()
    return [{"value": key, "count": int(count)} for key, count in rows]


__all__ = [
    "applications_summary",
    "dashboard_summary",
    "deadline_calendar",
    "top_organizations",
]
