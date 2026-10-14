"""Watchlist and notification endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.persistence.models import Watchlist
from app.schemas.watchlist import (
    NotificationRead,
    WatchlistCreate,
    WatchlistRead,
    WatchlistUpdate,
)
from app.services import watchlists as service

router = APIRouter(tags=["watchlists"])


@router.get("/watchlists", response_model=list[WatchlistRead], summary="List watchlists")
def list_watchlists(session: DbSession) -> list[WatchlistRead]:
    return [WatchlistRead.model_validate(row) for row in service.list_watchlists(session)]


@router.post(
    "/watchlists", response_model=WatchlistRead, status_code=201, summary="Create a watchlist"
)
def create_watchlist(payload: WatchlistCreate, session: DbSession) -> WatchlistRead:
    watchlist = service.create_watchlist(
        session,
        name=payload.name,
        description=payload.description,
        query=payload.query,
        enabled=payload.enabled,
    )
    return WatchlistRead.model_validate(watchlist)


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistRead, summary="Update a watchlist")
def update_watchlist(
    watchlist_id: int, payload: WatchlistUpdate, session: DbSession
) -> WatchlistRead:
    watchlist = _get(session, watchlist_id)
    service.update_watchlist(session, watchlist, **payload.model_dump(exclude_unset=True))
    return WatchlistRead.model_validate(watchlist)


@router.delete("/watchlists/{watchlist_id}", status_code=204, summary="Delete a watchlist")
def delete_watchlist(watchlist_id: int, session: DbSession) -> None:
    service.delete_watchlist(session, _get(session, watchlist_id))


@router.post(
    "/watchlists/check", summary="Run the watchlist check now (dashboard notifications)"
)
def run_check(session: DbSession) -> dict[str, int]:
    created = service.check_watchlists(session)
    session.commit()
    return {"notifications_created": created}


@router.get("/notifications", response_model=list[NotificationRead], summary="List notifications")
def list_notifications(
    session: DbSession,
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[NotificationRead]:
    rows = service.list_notifications(session, unread_only=unread_only, limit=limit)
    return [NotificationRead.model_validate(row) for row in rows]


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: int, session: DbSession) -> NotificationRead:
    from app.persistence.models import Notification

    row = session.get(Notification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="notification not found")
    service.mark_notification_read(session, row)
    return NotificationRead.model_validate(row)


@router.post("/notifications/read-all", summary="Mark every notification as read")
def mark_all_read(session: DbSession) -> dict[str, int]:
    count = service.mark_all_read(session)
    session.commit()
    return {"marked": count}


def _get(session: Session, watchlist_id: int) -> Watchlist:
    row = session.get(Watchlist, watchlist_id)
    if row is None:
        raise HTTPException(status_code=404, detail="watchlist not found")
    return row


__all__ = ["router"]
