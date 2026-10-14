"""Application tracker: status transitions, notes, and follow-ups.

Security note: this stores no passwords or portal credentials — only the
information you are willing to keep locally (docs/DATA_MODEL.md, SECURITY.md).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ApplicationStatus
from app.logging_config import get_logger
from app.persistence.models import Application, Opportunity, utcnow

log = get_logger("openpath.services.applications")

DEFAULT_STATUS = ApplicationStatus.DISCOVERED

# Statuses that imply the user has committed to applying.
COMMITTED_STATUSES = {
    ApplicationStatus.PREPARING,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
    ApplicationStatus.ACCEPTED,
}


def get_application(session: Session, opportunity_id: int) -> Application | None:
    return session.execute(
        select(Application).where(Application.opportunity_id == opportunity_id)
    ).scalar_one_or_none()


def upsert_application(
    session: Session,
    opportunity: Opportunity,
    *,
    status: ApplicationStatus | None = None,
    applied_at: Any = None,
    follow_up_at: Any = None,
    documents_required: list[str] | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    notes: str | None = None,
) -> Application:
    """Create or update the tracker row for an opportunity."""
    application = get_application(session, opportunity.id)
    if application is None:
        application = Application(
            opportunity_id=opportunity.id,
            status=status or DEFAULT_STATUS,
        )
        session.add(application)
    if status is not None:
        application.status = status
        if status is ApplicationStatus.SAVED:
            opportunity.is_saved = True
    if applied_at is not None:
        application.applied_at = applied_at
    if follow_up_at is not None:
        application.follow_up_at = follow_up_at
    if documents_required is not None:
        application.documents_required = documents_required
    if contact_name is not None:
        application.contact_name = contact_name
    if contact_email is not None:
        application.contact_email = contact_email
    if notes is not None:
        application.notes = notes
    application.updated_at = utcnow()
    session.flush()
    return application


def set_status(
    session: Session,
    opportunity: Opportunity,
    status: ApplicationStatus,
    *,
    notes: str | None = None,
) -> Application:
    return upsert_application(session, opportunity, status=status, notes=notes)


def list_applications(
    session: Session,
    *,
    statuses: list[ApplicationStatus] | None = None,
    limit: int = 200,
) -> list[tuple[Application, Opportunity]]:
    stmt = (
        select(Application, Opportunity)
        .join(Opportunity, Application.opportunity_id == Opportunity.id)
        .order_by(Application.updated_at.desc())
        .limit(limit)
    )
    if statuses:
        stmt = stmt.where(Application.status.in_(statuses))
    return [(application, opportunity) for application, opportunity in session.execute(stmt).all()]


def delete_application(session: Session, opportunity_id: int) -> bool:
    application = get_application(session, opportunity_id)
    if application is None:
        return False
    session.delete(application)
    session.flush()
    return True


def toggle_saved(session: Session, opportunity: Opportunity, *, saved: bool | None = None) -> bool:
    """Mark/unmark an opportunity as saved; keeps the tracker row in sync."""
    opportunity.is_saved = (not opportunity.is_saved) if saved is None else saved
    if opportunity.is_saved and get_application(session, opportunity.id) is None:
        session.add(Application(opportunity_id=opportunity.id, status=ApplicationStatus.SAVED))
    session.flush()
    return opportunity.is_saved


__all__ = [
    "COMMITTED_STATUSES",
    "DEFAULT_STATUS",
    "delete_application",
    "get_application",
    "list_applications",
    "set_status",
    "toggle_saved",
    "upsert_application",
]
