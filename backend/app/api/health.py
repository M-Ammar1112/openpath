"""Health and metadata endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.config import settings
from app.connectors.registry import available_connector_types
from app.enums import ApplicationStatus, FundingType, OpportunityType, SortField
from app.persistence.models import Opportunity, Source

router = APIRouter(tags=["system"])


@router.get("/health", summary="Service health")
def health(session: DbSession) -> dict[str, object]:
    counts = {
        "opportunities": int(
            session.execute(select(func.count()).select_from(Opportunity)).scalar_one()
        ),
        "sources": int(session.execute(select(func.count()).select_from(Source)).scalar_one()),
    }
    return {
        "status": "ok",
        "environment": settings.openpath_env,
        "time": datetime.now(UTC).isoformat(),
        "counts": counts,
    }


@router.get("/meta", summary="Enumerations and capabilities for the UI")
def meta() -> dict[str, object]:
    return {
        "opportunity_types": [item.value for item in OpportunityType],
        "funding_types": [item.value for item in FundingType],
        "application_statuses": [item.value for item in ApplicationStatus],
        "sort_fields": [item.value for item in SortField],
        "connector_types": available_connector_types(),
        "scheduler_enabled": settings.scheduler_enabled,
    }


__all__ = ["router"]
