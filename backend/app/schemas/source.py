"""Source management and ingestion-result schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import SourceCategory, SourceStatus


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    category: SourceCategory
    connector_type: str
    endpoint_url: str | None = None
    description: str | None = None
    license_notes: str | None = None
    enabled: bool
    fetch_interval_seconds: int
    rate_limit_seconds: float
    status: SourceStatus
    last_fetched_at: datetime | None = None
    last_error: str | None = None
    options: dict[str, object] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    fetch_interval_seconds: int | None = Field(default=None, ge=300, le=604800)
    rate_limit_seconds: float | None = Field(default=None, ge=0, le=120)


class SourceFetchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    http_status: int | None = None
    records_fetched: int
    records_new: int
    records_updated: int
    records_duplicate: int
    records_invalid: int
    error: str | None = None
    duration_ms: int | None = None


class SourceRunResultRead(BaseModel):
    source_key: str
    status: str
    fetched: int
    parsed: int
    new: int
    updated: int
    duplicates: int
    invalid: int
    error: str | None = None
    duration_ms: int
    messages: list[str] = Field(default_factory=list)


class RefreshSummary(BaseModel):
    sources: list[SourceRunResultRead]
    total_new: int
    total_updated: int
    errors: int


__all__ = [
    "RefreshSummary",
    "SourceFetchRead",
    "SourceRead",
    "SourceRunResultRead",
    "SourceUpdate",
]
