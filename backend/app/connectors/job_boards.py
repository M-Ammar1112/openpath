"""JSON job-board connectors (Ashby, Arbeitnow, Remotive).

All three publish public JSON endpoints (verified September 2026) and are
consumed read-only with an identifying User-Agent and rate limiting.
Descriptions are converted from HTML to plain text; raw source HTML is
never rendered in the frontend.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.connectors.base import NormalizedOpportunity, ParsedItem
from app.connectors.json_api import JsonApiConnector
from app.core.html import html_to_text
from app.enums import FundingType, OpportunityType
from app.normalize.fields import extract_skills, infer_opportunity_type

# Employment-type wording -> opportunity type (interns intern, others work).
_EMPLOYMENT_TYPE_MAP: tuple[tuple[str, OpportunityType], ...] = (
    ("intern", OpportunityType.INTERNSHIP),
    ("co-op", OpportunityType.INTERNSHIP),
    ("working student", OpportunityType.INTERNSHIP),
)


class _JobBoardConnector(JsonApiConnector):
    """Shared behaviour for job-board JSON APIs."""

    default_organization: ClassVar[str | None] = None

    def _skills(self, *texts: str | None) -> list[str]:
        vocab = self.options.get("skills") or []
        joined = " \n ".join(t for t in texts if t)
        return extract_skills(joined, vocab)

    def _remote_status(self, *, is_remote: Any = None, workplace: Any = None) -> str | None:
        if is_remote is True:
            return "remote"
        value = str(workplace or "").lower().replace("-", "")
        if value in {"remote", "hybrid", "onsite"}:
            return value
        return None

    def _employment_type(self, raw_types: Any) -> OpportunityType:
        joined = " ".join(raw_types) if isinstance(raw_types, list) else str(raw_types or "")
        lowered = joined.lower()
        for marker, kind in _EMPLOYMENT_TYPE_MAP:
            if marker in lowered:
                return kind
        return OpportunityType.INDUSTRY_JOB


class AshbyConnector(_JobBoardConnector):
    """Ashby-hosted company job boards (semiconductor / AI-chip employers).

    Endpoint pattern:
        https://api.ashbyhq.com/posting-api/job-board/<board>
    """

    connector_type: ClassVar[str] = "ashby"
    items_key: ClassVar[str] = "jobs"

    def to_parsed_item(self, raw: dict[str, Any]) -> ParsedItem | None:
        title = str(raw.get("title") or "").strip()
        url = raw.get("jobUrl") or raw.get("applyUrl")
        if not title or not url:
            return None
        address_obj = raw.get("address")
        address: dict[str, Any] = {}
        if isinstance(address_obj, dict):
            postal = address_obj.get("postalAddress")
            if isinstance(postal, dict):
                address = postal
        return ParsedItem(
            external_id=str(raw["id"]) if raw.get("id") else None,
            title=title,
            link=str(url),
            summary=html_to_text(raw.get("descriptionHtml") or raw.get("descriptionPlain")),
            published_at=str(raw.get("publishedAt") or ""),
            extra={
                "organization": self.options.get("organization")
                or self.options.get("board"),
                "country": address.get("addressCountry"),
                "city": address.get("addressLocality"),
                "department": raw.get("department") or raw.get("team"),
                "employment_type": raw.get("employmentType"),
                "is_remote": raw.get("isRemote"),
                "workplace_type": raw.get("workplaceType"),
                "apply_url": raw.get("applyUrl"),
            },
        )

    def normalize(self, item: ParsedItem) -> NormalizedOpportunity:
        extra = item.extra
        description = item.summary
        opportunity_type = self._employment_type(extra.get("employment_type"))
        if opportunity_type is OpportunityType.INDUSTRY_JOB and description:
            inferred = infer_opportunity_type(f"{item.title} {description}")
            if inferred in {
                OpportunityType.INTERNSHIP,
                OpportunityType.ACADEMIC_JOB,
                OpportunityType.RESEARCH_POSITION,
            }:
                opportunity_type = inferred
        return NormalizedOpportunity(
            title=item.title,
            official_url=item.link,
            opportunity_type=opportunity_type,
            organization=extra.get("organization") or "Ashby employer",
            country=extra.get("country"),
            city=extra.get("city"),
            field=extra.get("department"),
            funding_type=FundingType.PAID_POSITION,
            funding_type_raw="salaried position",
            remote_status=self._remote_status(
                is_remote=extra.get("is_remote"), workplace=extra.get("workplace_type")
            ),
            skills=self._skills(item.title, description, extra.get("department")),
            tags=[t for t in (extra.get("department"), extra.get("employment_type")) if t],
            description=description,
            source_key="",
            source_name="",
            external_id=item.external_id,
            raw_payload={
                "title": item.title,
                "url": item.link,
                "apply_url": extra.get("apply_url"),
                "published_at": item.published_at,
                "department": extra.get("department"),
                "employment_type": extra.get("employment_type"),
            },
        )


class ArbeitnowConnector(_JobBoardConnector):
    """Arbeitnow public job-board JSON API (European employers)."""

    connector_type: ClassVar[str] = "arbeitnow"
    items_key: ClassVar[str] = "data"

    def to_parsed_item(self, raw: dict[str, Any]) -> ParsedItem | None:
        title = str(raw.get("title") or "").strip()
        url = raw.get("url")
        if not title or not url:
            return None
        return ParsedItem(
            external_id=str(raw.get("slug") or ""),
            title=title,
            link=str(url),
            summary=html_to_text(raw.get("description")),
            published_at=str(raw.get("created_at") or ""),
            extra={
                "organization": raw.get("company_name"),
                "location": raw.get("location"),
                "tags": raw.get("tags") or [],
                "job_types": raw.get("job_types") or [],
                "is_remote": raw.get("remote"),
            },
        )

    def normalize(self, item: ParsedItem) -> NormalizedOpportunity:
        extra = item.extra
        location = str(extra.get("location") or "")
        return NormalizedOpportunity(
            title=item.title,
            official_url=item.link,
            opportunity_type=self._employment_type(extra.get("job_types")),
            organization=extra.get("organization"),
            country=self._country_from_location(location),
            city=self._city_from_location(location),
            funding_type=FundingType.PAID_POSITION,
            funding_type_raw="salaried position",
            remote_status=self._remote_status(is_remote=extra.get("is_remote")),
            skills=self._skills(item.title, item.summary, " ".join(extra.get("tags") or [])),
            tags=list(extra.get("tags") or []),
            description=item.summary,
            source_key="",
            source_name="",
            external_id=item.external_id,
            raw_payload={
                "title": item.title,
                "url": item.link,
                "location": location,
                "created_at": item.published_at,
            },
        )

    @staticmethod
    def _split_location(location: str) -> list[str]:
        return [part.strip() for part in location.split(",") if part.strip()]

    @classmethod
    def _country_from_location(cls, location: str) -> str | None:
        """Arbeitnow usually gives 'City, Country'; fall back to None."""
        parts = cls._split_location(location)
        return parts[-1] if len(parts) >= 2 else None

    @classmethod
    def _city_from_location(cls, location: str) -> str | None:
        parts = cls._split_location(location)
        return parts[0] if parts else None


class RemotiveConnector(_JobBoardConnector):
    """Remotive remote-jobs API.

    Remotive's terms allow sharing their jobs onward provided the original
    URL is linked back (OpenPath always stores and displays it); this
    connector therefore ships disabled by default.
    """

    connector_type: ClassVar[str] = "remotive"
    items_key: ClassVar[str] = "jobs"

    def to_parsed_item(self, raw: dict[str, Any]) -> ParsedItem | None:
        title = str(raw.get("title") or "").strip()
        url = raw.get("url")
        if not title or not url:
            return None
        return ParsedItem(
            external_id=str(raw.get("id") or ""),
            title=title,
            link=str(url),
            summary=html_to_text(raw.get("description")),
            published_at=str(raw.get("publication_date") or ""),
            extra={
                "organization": raw.get("company_name"),
                "location": raw.get("candidate_required_location"),
                "tags": raw.get("tags") or [],
                "category": raw.get("category"),
                "job_type": raw.get("job_type"),
                "salary": raw.get("salary"),
            },
        )

    def normalize(self, item: ParsedItem) -> NormalizedOpportunity:
        extra = item.extra
        return NormalizedOpportunity(
            title=item.title,
            official_url=item.link,
            opportunity_type=self._employment_type(extra.get("job_type")),
            organization=extra.get("organization"),
            field=extra.get("category"),
            funding_type=FundingType.PAID_POSITION,
            funding_type_raw="salaried position",
            remote_status="remote",
            skills=self._skills(item.title, item.summary, " ".join(extra.get("tags") or [])),
            tags=list(extra.get("tags") or []),
            description=item.summary,
            source_key="",
            source_name="",
            external_id=item.external_id,
            raw_payload={
                "title": item.title,
                "url": item.link,
                "location": extra.get("location"),
                "salary_text": extra.get("salary"),
                "published_at": item.published_at,
            },
        )


__all__ = [
    "ArbeitnowConnector",
    "AshbyConnector",
    "RemotiveConnector",
]

