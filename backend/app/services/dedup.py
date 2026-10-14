"""Duplicate detection and provenance-preserving upsert.

Strategy (cheapest first):
  1. exact canonical-URL match
  2. normalized (organization + title) key match
  3. token-similarity match (>= threshold) among recent rows in the same
     country, to catch the same opening advertised on several sites

Duplicates are never deleted: the surviving row keeps all source links.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import NormalizedOpportunity
from app.core.urls import canonicalize_url
from app.logging_config import get_logger
from app.normalize.text import jaccard, normalize_key, tokenize
from app.persistence.models import Opportunity, OpportunitySourceLink, Source, utcnow

log = get_logger("openpath.services.dedup")

SIMILARITY_THRESHOLD = 0.82
CANDIDATE_SCAN_LIMIT = 400


@dataclass(slots=True)
class UpsertOutcome:
    opportunity: Opportunity
    outcome: str  # "new" | "updated" | "duplicate"
    matched_by: str | None = None
    changed_fields: tuple[str, ...] = ()


def identity_keys(candidate: NormalizedOpportunity) -> tuple[str, str]:
    """(canonical_url, normalized org+title key)."""
    canonical = canonicalize_url(candidate.official_url)
    org_key = normalize_key(candidate.organization)
    title_key = normalize_key(candidate.title)
    return canonical, f"{org_key}|{title_key}".strip("|")


def find_duplicate(
    session: Session, candidate: NormalizedOpportunity
) -> tuple[Opportunity | None, str | None]:
    """Return (existing_opportunity, matched_by)."""
    canonical, org_title_key = identity_keys(candidate)

    by_url = (
        session.execute(select(Opportunity).where(Opportunity.canonical_url == canonical))
        .scalars()
        .first()
    )
    if by_url is not None:
        return by_url, "canonical_url"

    recent = list(
        session.execute(
            select(Opportunity)
            .where(Opportunity.is_archived.is_(False))
            .order_by(Opportunity.id.desc())
            .limit(CANDIDATE_SCAN_LIMIT)
        ).scalars()
    )
    for row in recent:
        row_key = f"{normalize_key(row.organization)}|{normalize_key(row.title)}"
        if row_key and row_key == org_title_key:
            return row, "org_title"

    candidate_tokens = tokenize(f"{candidate.organization or ''} {candidate.title}")
    candidate_country = normalize_key(candidate.country)
    best: tuple[float, Opportunity] | None = None
    for row in recent:
        row_country = normalize_key(row.country)
        if candidate_country and row_country and candidate_country != row_country:
            continue
        similarity = jaccard(candidate_tokens, tokenize(f"{row.organization or ''} {row.title}"))
        if similarity >= SIMILARITY_THRESHOLD and (best is None or similarity > best[0]):
            best = (similarity, row)
    if best is not None:
        return best[1], f"similarity:{best[0]:.2f}"
    return None, None


# Fields compared to decide whether an existing row changed.
_COMPARABLE_FIELDS: tuple[str, ...] = (
    "title",
    "organization",
    "country",
    "city",
    "opportunity_type",
    "field",
    "degree_level",
    "funding_type",
    "tuition",
    "stipend",
    "salary",
    "deadline",
    "opens_at",
    "eligibility",
    "required_degree",
    "gpa_requirement",
    "ielts_requirement",
    "toefl_requirement",
    "gre_requirement",
    "experience_requirement",
    "citizenship_restrictions",
    "research_area",
    "description",
)


def upsert_opportunity(
    session: Session,
    candidate: NormalizedOpportunity,
    *,
    source: Source,
) -> UpsertOutcome:
    """Insert a new opportunity or enrich the existing duplicate."""
    canonical, _ = identity_keys(candidate)
    existing, matched_by = find_duplicate(session, candidate)

    if existing is None:
        row = _create(session, candidate, canonical=canonical)
        _add_source_link(session, row, candidate, source)
        session.flush()
        return UpsertOutcome(opportunity=row, outcome="new")

    changed = _apply_changes(existing, candidate)
    _add_source_link(session, existing, candidate, source)
    existing.last_verified_at = utcnow()
    if changed:
        existing.updated_at = utcnow()
    session.flush()
    return UpsertOutcome(
        opportunity=existing,
        outcome="updated" if changed else "duplicate",
        matched_by=matched_by,
        changed_fields=tuple(changed),
    )


def _create(session: Session, candidate: NormalizedOpportunity, *, canonical: str) -> Opportunity:
    row = Opportunity(
        title=candidate.title,
        organization=candidate.organization,
        country=candidate.country,
        city=candidate.city,
        opportunity_type=candidate.opportunity_type,
        field=candidate.field,
        degree_level=candidate.degree_level,
        degree_level_raw=candidate.degree_level_raw,
        funding_type=candidate.funding_type,
        funding_type_raw=candidate.funding_type_raw,
        tuition=candidate.tuition,
        tuition_currency=candidate.tuition_currency,
        stipend=candidate.stipend,
        salary=candidate.salary,
        salary_currency=candidate.salary_currency,
        deadline=candidate.deadline,
        opens_at=candidate.opens_at,
        eligibility=candidate.eligibility,
        required_degree=candidate.required_degree,
        gpa_requirement=candidate.gpa_requirement,
        english_requirement=candidate.english_requirement,
        ielts_requirement=candidate.ielts_requirement,
        toefl_requirement=candidate.toefl_requirement,
        gre_requirement=candidate.gre_requirement,
        experience_requirement=candidate.experience_requirement,
        citizenship_restrictions=candidate.citizenship_restrictions,
        age_restrictions=candidate.age_restrictions,
        research_area=candidate.research_area,
        skills=list(candidate.skills),
        tags=list(candidate.tags),
        description=candidate.description,
        official_url=candidate.official_url,
        canonical_url=canonical,
        source_name=candidate.source_name,
        remote_status=candidate.remote_status,
        raw_payload=candidate.raw_payload,
    )
    session.add(row)
    return row


def _apply_changes(row: Opportunity, candidate: NormalizedOpportunity) -> list[str]:
    """Fill blanks and record genuine changes; never overwrite with less info."""
    changed: list[str] = []
    for field in _COMPARABLE_FIELDS:
        new_value = getattr(candidate, field, None)
        if new_value in (None, "", []):
            continue
        current = getattr(row, field)
        if current in (None, "", []):
            setattr(row, field, new_value)
            changed.append(field)
        elif str(current) != str(new_value):
            # Keep the most recently verified structured value but note the change.
            setattr(row, field, new_value)
            changed.append(field)
    if candidate.skills:
        merged = sorted({*(row.skills or []), *candidate.skills})
        if merged != (row.skills or []):
            row.skills = merged
            changed.append("skills")
    if candidate.tags:
        merged_tags = sorted({*(row.tags or []), *candidate.tags})
        if merged_tags != (row.tags or []):
            row.tags = merged_tags
            changed.append("tags")
    if candidate.raw_payload and row.raw_payload != candidate.raw_payload:
        row.raw_payload = candidate.raw_payload
    return changed


def _add_source_link(
    session: Session,
    row: Opportunity,
    candidate: NormalizedOpportunity,
    source: Source,
) -> None:
    """Attach provenance for this source occurrence (idempotent)."""
    link = session.execute(
        select(OpportunitySourceLink).where(
            OpportunitySourceLink.opportunity_id == row.id,
            OpportunitySourceLink.source_key == source.key,
            OpportunitySourceLink.source_url == candidate.official_url,
        )
    ).scalar_one_or_none()
    if link is not None:
        link.last_seen_at = utcnow()
        return
    session.add(
        OpportunitySourceLink(
            opportunity_id=row.id,
            source_key=source.key,
            source_url=candidate.official_url,
            external_id=candidate.external_id,
        )
    )


__all__ = [
    "CANDIDATE_SCAN_LIMIT",
    "SIMILARITY_THRESHOLD",
    "UpsertOutcome",
    "find_duplicate",
    "identity_keys",
    "upsert_opportunity",
]

