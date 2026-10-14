"""Application-tracker endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.enums import ApplicationStatus
from app.schemas.application import (
    ApplicationStatusUpdate,
    ApplicationUpsert,
    ApplicationWithOpportunity,
)
from app.services import applications as service
from app.services.query import get_opportunity

router = APIRouter(prefix="/applications", tags=["applications"])


def _pair_payload(application: object, opportunity: object) -> ApplicationWithOpportunity:
    payload = ApplicationWithOpportunity(
        **{
            field: getattr(application, field)
            for field in ApplicationWithOpportunity.model_fields
            if field != "opportunity"
        },
        opportunity=opportunity,
    )
    return payload


@router.get("", response_model=list[ApplicationWithOpportunity], summary="List tracked applications")
def list_applications(
    session: DbSession,
    status: list[ApplicationStatus] = Query(default=[]),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ApplicationWithOpportunity]:
    rows = service.list_applications(session, statuses=list(status) or None, limit=limit)
    return [_pair_payload(application, opportunity) for application, opportunity in rows]


@router.put(
    "/{opportunity_id}",
    response_model=ApplicationWithOpportunity,
    summary="Create or update the tracker row",
)
def upsert_application(
    opportunity_id: int, payload: ApplicationUpsert, session: DbSession
) -> ApplicationWithOpportunity:
    opportunity = get_opportunity(session, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    application = service.upsert_application(
        session, opportunity, **payload.model_dump(exclude_unset=True)
    )
    session.flush()
    return _pair_payload(application, opportunity)


@router.post(
    "/{opportunity_id}/status",
    response_model=ApplicationWithOpportunity,
    summary="Set application status",
)
def set_status(
    opportunity_id: int, payload: ApplicationStatusUpdate, session: DbSession
) -> ApplicationWithOpportunity:
    opportunity = get_opportunity(session, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    application = service.set_status(session, opportunity, payload.status, notes=payload.notes)
    session.flush()
    return _pair_payload(application, opportunity)


@router.delete("/{opportunity_id}", status_code=204, summary="Delete the tracker row")
def delete_application(opportunity_id: int, session: DbSession) -> None:
    if not service.delete_application(session, opportunity_id):
        raise HTTPException(status_code=404, detail="application not found")


__all__ = ["router"]
