"""Pydantic schemas for opportunity read/write payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.urls import validate_http_url
from app.enums import FreshnessStatus, FundingType, OpportunityType


class ScoreReasonRead(BaseModel):
    signal: str
    label: str
    points: float


class SourceLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_key: str
    source_url: str
    first_seen_at: datetime
    last_seen_at: datetime


class OpportunityBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    organization: str | None = None
    country: str | None = None
    city: str | None = None
    opportunity_type: OpportunityType
    field: str | None = None
    degree_level: str | None = None
    funding_type: FundingType
    funding_type_raw: str | None = None
    tuition: float | None = None
    tuition_currency: str | None = None
    stipend: float | None = None
    salary: float | None = None
    salary_currency: str | None = None
    deadline: date | None = None
    opens_at: date | None = None
    relevance_score: float
    confidence_score: float
    freshness_status: FreshnessStatus
    is_saved: bool
    remote_status: str | None = None
    source_name: str
    official_url: str
    discovered_at: datetime
    updated_at: datetime
    last_verified_at: datetime


class OpportunityListItem(OpportunityBase):
    """Compact row for tables/lists."""

    skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score_reasons: list[ScoreReasonRead] = Field(default_factory=list)


class OpportunityDetail(OpportunityBase):
    """Full record for the detail view."""

    description: str | None = None
    eligibility: str | None = None
    required_degree: str | None = None
    gpa_requirement: str | None = None
    english_requirement: str | None = None
    ielts_requirement: str | None = None
    toefl_requirement: str | None = None
    gre_requirement: str | None = None
    experience_requirement: str | None = None
    citizenship_restrictions: str | None = None
    age_restrictions: str | None = None
    research_area: str | None = None
    skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score_reasons: list[ScoreReasonRead] = Field(default_factory=list)
    notes: str | None = None
    is_archived: bool = False
    source_links: list[SourceLinkRead] = Field(default_factory=list)


class OpportunityPage(BaseModel):
    items: list[OpportunityListItem]
    total: int
    limit: int
    offset: int


class OpportunityUpdate(BaseModel):
    """User-editable fields (never source facts)."""

    notes: str | None = Field(default=None, max_length=8000)
    is_saved: bool | None = None
    is_archived: bool | None = None

    @field_validator("notes")
    @classmethod
    def _clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class OpportunityCreate(BaseModel):
    """Manual creation of an opportunity (used by import UI/tests)."""

    title: str = Field(min_length=3, max_length=600)
    official_url: str
    organization: str | None = None
    country: str | None = None
    city: str | None = None
    opportunity_type: OpportunityType = OpportunityType.OTHER
    funding_type: FundingType = FundingType.UNKNOWN
    funding_type_raw: str | None = None
    deadline: date | None = None
    description: str | None = None
    field: str | None = None
    degree_level: str | None = None
    skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None

    @field_validator("official_url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        return validate_http_url(value, field="official_url")


__all__ = [
    "OpportunityCreate",
    "OpportunityDetail",
    "OpportunityListItem",
    "OpportunityPage",
    "OpportunityUpdate",
    "ScoreReasonRead",
    "SourceLinkRead",
]
