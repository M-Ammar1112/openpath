"""SQLAlchemy models — the OpenPath data model.

See docs/DATA_MODEL.md. All timestamps are timezone-aware UTC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.enums import (
    ApplicationStatus,
    FreshnessStatus,
    FundingType,
    OpportunityType,
    SourceCategory,
    SourceStatus,
    TaxonomyKind,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}


class Profile(Base):
    """Single-row configurable user profile (editable via the Profile page)."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), default="OpenPath user")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Interests
    preferred_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    research_interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Education
    degrees: Mapped[list[str]] = mapped_column(JSON, default=list)
    degree_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    years_experience: Mapped[float] = mapped_column(Float, default=0.0)

    # Preferences
    desired_program_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    desired_job_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    funding_preference: Mapped[str] = mapped_column(String(30), default="any")
    preferred_countries: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_countries: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_tuition: Mapped[float | None] = mapped_column(Float, nullable=True)
    desired_salary: Mapped[float | None] = mapped_column(Float, nullable=True)
    willingness_to_relocate: Mapped[bool] = mapped_column(Boolean, default=True)
    remote_preference: Mapped[str] = mapped_column(String(20), default="any")

    # Background / tests
    nationality: Mapped[str | None] = mapped_column(String(80), nullable=True)
    current_country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    ielts_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    toefl_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gre_status: Mapped[str | None] = mapped_column(String(30), nullable=True)


class TaxonomyTerm(Base):
    """Configurable taxonomy: fields, skills, synonyms (seeded from YAML)."""

    __tablename__ = "taxonomy_terms"
    __table_args__ = (UniqueConstraint("kind", "term", name="uq_taxonomy_kind_term"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[TaxonomyKind] = mapped_column(Enum(TaxonomyKind))
    term: Mapped[str] = mapped_column(String(160))
    group: Mapped[str | None] = mapped_column(String(80), nullable=True)
    canonical: Mapped[str | None] = mapped_column(String(160), nullable=True)


class Source(Base):
    """A configured data source behind a SourceConnector."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[SourceCategory] = mapped_column(Enum(SourceCategory))
    connector_type: Mapped[str] = mapped_column(String(40))
    endpoint_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    fetch_interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    rate_limit_seconds: Mapped[float] = mapped_column(Float, default=2.0)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[SourceStatus] = mapped_column(Enum(SourceStatus), default=SourceStatus.IDLE)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    fetches: Mapped[list[SourceFetch]] = relationship(back_populates="source")


class SourceFetch(Base):
    """Audit record for each refresh attempt of a source."""

    __tablename__ = "source_fetches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_new: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    records_invalid: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[Source] = relationship(back_populates="fetches")


class Opportunity(Base):
    """The core normalized opportunity record."""

    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opp_deadline", "deadline"),
        Index("ix_opp_score", "relevance_score"),
        Index("ix_opp_type_funding", "opportunity_type", "funding_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str] = mapped_column(String(600))
    organization: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    opportunity_type: Mapped[OpportunityType] = mapped_column(Enum(OpportunityType), index=True)
    field: Mapped[str | None] = mapped_column(String(200), nullable=True)
    degree_level: Mapped[str | None] = mapped_column(String(60), nullable=True)
    degree_level_raw: Mapped[str | None] = mapped_column(String(160), nullable=True)

    funding_type: Mapped[FundingType] = mapped_column(Enum(FundingType), default=FundingType.UNKNOWN)
    funding_type_raw: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tuition: Mapped[float | None] = mapped_column(Float, nullable=True)
    tuition_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    stipend: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    opens_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Requirements (strings preserve source nuance; scores are numeric when given)
    eligibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_degree: Mapped[str | None] = mapped_column(String(200), nullable=True)
    gpa_requirement: Mapped[str | None] = mapped_column(String(80), nullable=True)
    english_requirement: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ielts_requirement: Mapped[str | None] = mapped_column(String(60), nullable=True)
    toefl_requirement: Mapped[str | None] = mapped_column(String(60), nullable=True)
    gre_requirement: Mapped[str | None] = mapped_column(String(60), nullable=True)
    experience_requirement: Mapped[str | None] = mapped_column(String(200), nullable=True)
    citizenship_restrictions: Mapped[str | None] = mapped_column(String(300), nullable=True)
    age_restrictions: Mapped[str | None] = mapped_column(String(120), nullable=True)

    research_area: Mapped[str | None] = mapped_column(String(300), nullable=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance / links
    official_url: Mapped[str] = mapped_column(String(1000))
    canonical_url: Mapped[str] = mapped_column(String(1000), index=True)
    source_name: Mapped[str] = mapped_column(String(160), index=True)
    remote_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Freshness
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    freshness_status: Mapped[FreshnessStatus] = mapped_column(
        Enum(FreshnessStatus), default=FreshnessStatus.DISCOVERED, index=True
    )

    # Ranking
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # User state
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    source_links: Mapped[list[OpportunitySourceLink]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )
    application: Mapped[Application | None] = relationship(
        back_populates="opportunity", uselist=False, cascade="all, delete-orphan"
    )


class OpportunitySourceLink(Base):
    """Provenance: one row per source occurrence. Survives dedup merges."""

    __tablename__ = "opportunity_source_links"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "source_key", "source_url", name="uq_link_occurrence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(80), index=True)
    source_url: Mapped[str] = mapped_column(String(1000))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    opportunity: Mapped[Opportunity] = relationship(back_populates="source_links")


class Application(Base):
    """Application tracker row for an opportunity (no credentials stored)."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id"), unique=True, index=True
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.DISCOVERED, index=True
    )
    applied_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    follow_up_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    documents_required: Mapped[list[str]] = mapped_column(JSON, default=list)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="application")


class Watchlist(Base):
    """Saved search that periodically emits notifications."""

    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notifications: Mapped[list[Notification]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class Notification(Base):
    """Dashboard notification produced by a watchlist match."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "opportunity_id", name="uq_notification_match"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"), index=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    watchlist: Mapped[Watchlist] = relationship(back_populates="notifications")


__all__ = [
    "Application",
    "Base",
    "Notification",
    "Opportunity",
    "OpportunitySourceLink",
    "Profile",
    "Source",
    "SourceFetch",
    "TaxonomyTerm",
    "Watchlist",
    "utcnow",
]