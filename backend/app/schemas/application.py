"""Application-tracker schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import ApplicationStatus
from app.schemas.opportunity import OpportunityListItem


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opportunity_id: int
    status: ApplicationStatus
    applied_at: date | None = None
    follow_up_at: date | None = None
    documents_required: list[str] = Field(default_factory=list)
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None
    updated_at: datetime


class ApplicationWithOpportunity(ApplicationRead):
    opportunity: OpportunityListItem


class ApplicationUpsert(BaseModel):
    """Fields you can set from the UI. Credentials are never accepted here."""

    status: ApplicationStatus | None = None
    applied_at: date | None = None
    follow_up_at: date | None = None
    documents_required: list[str] | None = Field(default=None, max_length=50)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=254)
    notes: str | None = Field(default=None, max_length=8000)

    @field_validator("contact_email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if "@" not in text or "." not in text.split("@")[-1]:
            raise ValueError("contact_email must look like an email address")
        return text



class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    notes: str | None = Field(default=None, max_length=8000)


__all__ = [
    "ApplicationRead",
    "ApplicationStatusUpdate",
    "ApplicationUpsert",
    "ApplicationWithOpportunity",
]
