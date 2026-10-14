"""Watchlists (saved searches) and the dashboard notification channel.

The notification layer is intentionally pluggable: `check_watchlists`
produces `Notification` rows (dashboard channel); email/Telegram/desktop
notifiers can consume the same rows later without touching this logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import FundingType, FreshnessStatus, OpportunityType, SortField
from app.logging_config import get_logger
from app.persistence.models import Notification, Opportunity, Watchlist
from app.services.query import OpportunityFilters, list_opportunities

log = get_logger("openpath.services.watchlists")

MAX_NOTIFICATIONS_PER_WATCHLIST = 25


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def filters_from_query(query: dict[str, Any] | None) -> OpportunityFilters:
    """Translate a stored watchlist query into OpportunityFilters.

    Unknown keys are ignored and invalid enum values degrade to "no filter"
    rather than crashing the scheduled job.
    """
    data = query or {}
    filters = OpportunityFilters()
    filters.q = data.get("q") or data.get("search")
    filters.country = _as_list(data.get("country"))
    filters.organization = data.get("organization")
    filters.degree_level = data.get("degree_level")
    filters.field_ = data.get("field")
    filters.source_key = data.get("source_key")
    filters.remote_status = data.get("remote_status")
    filters.only_saved = bool(data.get("only_saved", False))
    filters.min_score = float(data["min_score"]) if data.get("min_score") is not None else None
    filters.max_tuition = (
        float(data["max_tuition"]) if data.get("max_tuition") is not None else None
    )
    for key, enum_type, target in (
        ("opportunity_type", OpportunityType, filters.opportunity_type),
        ("funding_type", FundingType, filters.funding_type),
        ("freshness", FreshnessStatus, filters.freshness),
    ):
        for value in _as_list(data.get(key)):
            try:
                target.append(enum_type(value))
            except ValueError:
                log.warning("watchlist_filter_ignored", extra={"key": key, "value": value})
    try:
        filters.sort = SortField(data["sort"]) if data.get("sort") else SortField.NEWEST
    except ValueError:
        filters.sort = SortField.NEWEST
    filters.limit = MAX_NOTIFICATIONS_PER_WATCHLIST
    return filters


def list_watchlists(session: Session) -> list[Watchlist]:
    return list(session.execute(select(Watchlist).order_by(Watchlist.id)).scalars())


def create_watchlist(
    session: Session,
    *,
    name: str,
    query: dict[str, Any],
    description: str | None = None,
    enabled: bool = True,
) -> Watchlist:
    watchlist = Watchlist(name=name, description=description, query=query, enabled=enabled)
    session.add(watchlist)
    session.flush()
    return watchlist


def update_watchlist(
    session: Session,
    watchlist: Watchlist,
    *,
    name: str | None = None,
    description: str | None = None,
    query: dict[str, Any] | None = None,
    enabled: bool | None = None,
) -> Watchlist:
    if name is not None:
        watchlist.name = name
    if description is not None:
        watchlist.description = description
    if query is not None:
        watchlist.query = query
    if enabled is not None:
        watchlist.enabled = enabled
    session.flush()
    return watchlist


def delete_watchlist(session: Session, watchlist: Watchlist) -> None:
    session.delete(watchlist)
    session.flush()


def check_watchlists(session: Session, *, lookback_days: int = 14) -> int:
    """Emit notifications for new matches. Returns notifications created."""
    created = 0
    now = datetime.now(UTC)
    for watchlist in list_watchlists(session):
        if not watchlist.enabled:
            continue
        filters = filters_from_query(watchlist.query)
        since = watchlist.last_checked_at or (now - timedelta(days=lookback_days))
        rows, _ = list_opportunities(session, filters)
        for opportunity in rows:
            if opportunity.discovered_at is None or opportunity.discovered_at <= since:
                continue
            if _notification_exists(session, watchlist.id, opportunity.id):
                continue
            session.add(
                Notification(
                    watchlist_id=watchlist.id,
                    opportunity_id=opportunity.id,
                    message=_message(watchlist.name, opportunity),
                )
            )
            created += 1
        watchlist.last_checked_at = now
    session.flush()
    if created:
        log.info("watchlist_notifications_created", extra={"count": created})
    return created


def _message(watchlist_name: str, opportunity: Opportunity) -> str:
    location = opportunity.country or "location unknown"
    return (
        f"[{watchlist_name}] {opportunity.title} — "
        f"{opportunity.organization or 'unknown organisation'} ({location}), "
        f"match {opportunity.relevance_score:.0f}/100"
    )


def _notification_exists(session: Session, watchlist_id: int, opportunity_id: int) -> bool:
    return (
        session.execute(
            select(Notification.id).where(
                Notification.watchlist_id == watchlist_id,
                Notification.opportunity_id == opportunity_id,
            )
        ).first()
        is not None
    )


def list_notifications(
    session: Session, *, unread_only: bool = False, limit: int = 100
) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return list(session.execute(stmt).scalars())


def mark_notification_read(session: Session, notification: Notification) -> Notification:
    notification.is_read = True
    session.flush()
    return notification


def mark_all_read(session: Session) -> int:
    rows = list(
        session.execute(select(Notification).where(Notification.is_read.is_(False))).scalars()
    )
    for row in rows:
        row.is_read = True
    session.flush()
    return len(rows)


__all__ = [
    "MAX_NOTIFICATIONS_PER_WATCHLIST",
    "check_watchlists",
    "create_watchlist",
    "delete_watchlist",
    "filters_from_query",
    "list_notifications",
    "list_watchlists",
    "mark_all_read",
    "mark_notification_read",
    "update_watchlist",
]

