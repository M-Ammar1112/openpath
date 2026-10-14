"""Freshness lifecycle: discovered → updated → verified → stale → expired.

Historical records are never deleted; they are archived (see AD-9).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.enums import FreshnessStatus
from app.logging_config import get_logger
from app.persistence.models import Opportunity

log = get_logger("openpath.services.freshness")

DEFAULT_STALE_AFTER_DAYS = 21
DEFAULT_ARCHIVE_AFTER_DAYS = 120


def sweep_freshness(
    session: Session,
    *,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> dict[str, int]:
    """Recompute freshness statuses. Returns counts per transition."""
    today = datetime.now(UTC).date()
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=stale_after_days)
    counts = {"expired": 0, "stale": 0, "verified": 0}

    rows = list(
        session.execute(select(Opportunity).where(Opportunity.is_archived.is_(False))).scalars()
    )
    for row in rows:
        if row.deadline and row.deadline < today:
            if row.freshness_status is not FreshnessStatus.EXPIRED:
                row.freshness_status = FreshnessStatus.EXPIRED
                counts["expired"] += 1
            continue
        if row.last_verified_at and row.last_verified_at < stale_cutoff:
            if row.freshness_status is not FreshnessStatus.STALE:
                row.freshness_status = FreshnessStatus.STALE
                counts["stale"] += 1
            continue
        if row.freshness_status in {FreshnessStatus.STALE, FreshnessStatus.DISCOVERED, FreshnessStatus.UPDATED}:
            row.freshness_status = FreshnessStatus.VERIFIED
            counts["verified"] += 1
    session.flush()
    log.info("freshness_sweep_completed", extra=counts)
    return counts


def archive_long_expired(
    session: Session,
    *,
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
) -> int:
    """Archive (not delete) opportunities whose deadline passed long ago."""
    cutoff = datetime.now(UTC).date() - timedelta(days=archive_after_days)
    rows = list(
        session.execute(
            select(Opportunity).where(
                Opportunity.deadline.is_not(None),
                Opportunity.deadline < cutoff,
                Opportunity.is_archived.is_(False),
                or_(
                    Opportunity.freshness_status == FreshnessStatus.EXPIRED,
                    Opportunity.freshness_status == FreshnessStatus.STALE,
                ),
            )
        ).scalars()
    )
    for row in rows:
        row.is_archived = True
        row.freshness_status = FreshnessStatus.ARCHIVED
    session.flush()
    if rows:
        log.info("archived_expired", extra={"count": len(rows)})
    return len(rows)


def mark_verified(session: Session, opportunities: list[Opportunity]) -> int:
    """Explicitly confirm rows as freshly verified (e.g. after a refresh)."""
    now = datetime.now(UTC)
    for row in opportunities:
        row.last_verified_at = now
        if row.freshness_status not in {FreshnessStatus.EXPIRED, FreshnessStatus.ARCHIVED}:
            row.freshness_status = FreshnessStatus.VERIFIED
    session.flush()
    return len(opportunities)


__all__ = [
    "DEFAULT_ARCHIVE_AFTER_DAYS",
    "DEFAULT_STALE_AFTER_DAYS",
    "archive_long_expired",
    "mark_verified",
    "sweep_freshness",
]
