"""Scoring service: applies a ranking strategy to stored opportunities."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import FundingType
from app.logging_config import get_logger
from app.persistence.models import Opportunity, Profile, utcnow
from app.ranking.lexical import LexicalRankingStrategy
from app.ranking.strategy import RankingStrategy
from app.services.seed import seed_profile
from app.services.taxonomy import synonym_map

log = get_logger("openpath.services.scoring")


def get_profile(session: Session) -> Profile:
    """Return the single profile, seeding the default if necessary."""
    profile = session.execute(select(Profile).order_by(Profile.id).limit(1)).scalar_one_or_none()
    if profile is None:
        profile = seed_profile(session)
        session.flush()
    return profile


def build_strategy(session: Session) -> RankingStrategy:
    """Default deterministic strategy, synonym-expanded from taxonomy."""
    return LexicalRankingStrategy(synonym_map(session))


def confidence_for(opportunity: Opportunity) -> float:
    """How complete/verifiable a record is (0-1). Not a relevance measure."""
    checks = [
        bool(opportunity.official_url),
        bool(opportunity.description and len(opportunity.description) > 120),
        bool(opportunity.deadline),
        opportunity.funding_type is not FundingType.UNKNOWN,
        bool(opportunity.organization),
        bool(opportunity.country),
        bool(opportunity.eligibility or opportunity.required_degree),
        bool(opportunity.source_links),
    ]
    return round(sum(1 for c in checks if c) / len(checks), 2)


def score_opportunity(
    opportunity: Opportunity,
    profile: Profile,
    strategy: RankingStrategy,
) -> Opportunity:
    """Score a single opportunity in place and store the explanation."""
    result = strategy.score(opportunity, profile)
    opportunity.relevance_score = result.score
    opportunity.score_reasons = result.to_payload()
    opportunity.confidence_score = confidence_for(opportunity)
    opportunity.scored_at = datetime.now(UTC)
    return opportunity


def score_all(
    session: Session,
    *,
    only_unscored: bool = False,
    limit: int | None = None,
) -> int:
    """Re-score stored opportunities. Returns the number scored."""
    profile = get_profile(session)
    strategy = build_strategy(session)
    query = select(Opportunity).where(Opportunity.is_archived.is_(False))
    if only_unscored:
        query = query.where(Opportunity.scored_at.is_(None))
    query = query.order_by(Opportunity.id)
    if limit:
        query = query.limit(limit)
    rows = list(session.execute(query).scalars())
    for row in rows:
        score_opportunity(row, profile, strategy)
    if rows:
        log.info("scoring_completed", extra={"scored": len(rows), "strategy": strategy.name})
    return len(rows)


def rescore_after_profile_change(session: Session) -> int:
    """Re-score everything (profile edits can change every score)."""
    return score_all(session, only_unscored=False)


def touch_updated_at(profile: Profile) -> None:
    profile.updated_at = utcnow()


__all__ = [
    "build_strategy",
    "confidence_for",
    "get_profile",
    "rescore_after_profile_change",
    "score_all",
    "score_opportunity",
]
