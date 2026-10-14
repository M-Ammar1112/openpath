"""Source connector contract shared by every connector implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.enums import FundingType, OpportunityType
from app.core.urls import validate_http_url


@dataclass(slots=True)
class FetchContext:
    """Everything a connector needs to fetch."""

    endpoint_url: str | None
    source_key: str
    rate_limit_seconds: float = 2.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FetchedRecord:
    """One raw payload fetched from a source."""

    url: str
    content: bytes
    content_type: str = ""


class ParsedItem(BaseModel):
    """Source-specific parsed record, pre-normalization."""

    external_id: str | None = None
    title: str
    link: str
    summary: str | None = None
    published_at: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedOpportunity(BaseModel):
    """Canonical candidate produced by `connector.normalize()`.

    Validation (`connector.validate()`) rejects candidates missing critical
    fields before they reach the database.
    """

    title: str = Field(min_length=3, max_length=600)
    official_url: str
    opportunity_type: OpportunityType = OpportunityType.OTHER
    organization: str | None = None
    country: str | None = None
    city: str | None = None
    field: str | None = None
    degree_level: str | None = None
    degree_level_raw: str | None = None
    funding_type: FundingType = FundingType.UNKNOWN
    funding_type_raw: str | None = None
    tuition: float | None = None
    tuition_currency: str | None = None
    stipend: float | None = None
    salary: float | None = None
    salary_currency: str | None = None
    deadline: date | None = None
    opens_at: date | None = None
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
    description: str | None = None
    remote_status: str | None = None
    source_key: str
    source_name: str
    external_id: str | None = None
    raw_payload: dict[str, Any] | None = None

    @field_validator("official_url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        return validate_http_url(value, field="official_url")


class SourceConnector(ABC):
    """Common interface: fetch → parse → normalize → validate.

    Implementations must use `app.core.http.HttpClient` for all network
    access so robots/rate-limit/cache policy applies uniformly.
    """

    connector_type: str = "abstract"

    def __init__(self, *, endpoint_url: str | None = None, options: dict[str, Any] | None = None):
        self.endpoint_url = endpoint_url
        self.options = options or {}

    @abstractmethod
    async def fetch(self, ctx: FetchContext) -> list[FetchedRecord]:
        """Retrieve raw payloads (through the shared HTTP client)."""

    @abstractmethod
    def parse(self, record: FetchedRecord) -> list[ParsedItem]:
        """Turn a raw payload into parsed items. Pure function (fixture-testable)."""

    @abstractmethod
    def normalize(self, item: ParsedItem) -> NormalizedOpportunity:
        """Map a parsed item onto the canonical opportunity shape."""

    def validate(self, candidate: NormalizedOpportunity) -> list[str]:
        """Return validation errors (empty = valid). Override for source rules."""
        errors: list[str] = []
        if len(candidate.title.strip()) < 5:
            errors.append("title too short")
        if candidate.deadline and candidate.opens_at and candidate.deadline < candidate.opens_at:
            errors.append("deadline precedes opening date")
        return errors