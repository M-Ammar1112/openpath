"""Deterministic, explainable lexical ranking strategy.

Every deduction/bonus is recorded as a `ScoreReason` so the UI can show
"WHY IT MATCHES". Weights sum to 100; constraint violations subtract.
A future semantic strategy can replace this behind `RankingStrategy`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from app.enums import DegreeLevel, FundingType
from app.normalize.text import contains_term, tokenize
from app.persistence.models import Opportunity, Profile
from app.ranking.strategy import ScoreReason, ScoreResult

# Weight budget (max 100).
W_KEYWORDS = 35.0
W_FIELD = 15.0
W_DEGREE = 15.0
W_FUNDING = 10.0
W_LOCATION = 10.0
W_TIMELINE = 10.0

_DEGREE_RANK: dict[str, int] = {
    DegreeLevel.NONE.value: 0,
    DegreeLevel.BACHELORS.value: 1,
    "bachelor": 1,
    DegreeLevel.MASTERS.value: 2,
    "master": 2,
    DegreeLevel.DOCTORATE.value: 3,
    "phd": 3,
    "doctoral": 3,
    "any": 0,
    "unknown": 0,
}

_COUNTRY_ALIASES: dict[str, str] = {
    "usa": "united states",
    "us": "united states",
    "u.s.": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "nl": "netherlands",
    "de": "germany",
}


def _normalize_country(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    return _COUNTRY_ALIASES.get(key, key)


class LexicalRankingStrategy:
    """Keyword/skill/field/eligibility scoring with explicit reasons."""

    name = "lexical-v1"

    def __init__(self, synonym_map: dict[str, list[str]] | None = None) -> None:
        # canonical -> variants; used to expand profile terms
        self.synonym_map = synonym_map or {}

    # -- helpers --------------------------------------------------------
    def _expand(self, term: str) -> list[str]:
        variants = [term]
        for canonical, group in self.synonym_map.items():
            lowered = [g.lower() for g in group] + [canonical.lower()]
            if term.lower() in lowered:
                variants.extend([canonical, *group])
        seen: set[str] = set()
        unique: list[str] = []
        for variant in variants:
            key = variant.lower()
            if key not in seen:
                seen.add(key)
                unique.append(variant)
        return unique

    def _profile_terms(self, profile: Profile) -> list[tuple[str, str]]:
        """Return (term, category) pairs from the profile."""
        pairs: list[tuple[str, str]] = []
        for field in profile.preferred_fields or []:
            pairs.append((field, "field"))
        for skill in profile.skills or []:
            pairs.append((skill, "skill"))
        for interest in profile.research_interests or []:
            pairs.append((interest, "research"))
        for keyword in profile.preferred_keywords or []:
            pairs.append((keyword, "keyword"))
        return pairs

    @staticmethod
    def _haystack(opportunity: Opportunity) -> str:
        parts = [
            opportunity.title,
            opportunity.description,
            opportunity.field,
            opportunity.research_area,
            opportunity.organization,
            " ".join(opportunity.skills or []),
            " ".join(opportunity.tags or []),
        ]
        return " \n ".join(p for p in parts if p)

    def _match_terms(self, opportunity: Opportunity, profile: Profile) -> list[tuple[str, str]]:
        haystack = self._haystack(opportunity)
        matched: list[tuple[str, str]] = []
        for term, category in self._profile_terms(profile):
            for variant in self._expand(term):
                if contains_term(haystack, variant):
                    matched.append((term, category))
                    break
        return matched

    def _keyword_score(self, matched: list[tuple[str, str]], profile: Profile) -> tuple[float, list[ScoreReason]]:
        total_terms = max(1, len(self._profile_terms(profile)))
        denominator = min(total_terms, 6)
        ratio = min(1.0, len(matched) / denominator)
        points = W_KEYWORDS * ratio
        reasons: list[ScoreReason] = []
        for term, category in matched[:8]:
            label = {
                "skill": f"{term} is one of your skills",
                "field": f"{term} matches your preferred field",
                "research": f"{term} matches your research interests",
                "keyword": f"'{term}' keyword mentioned",
            }[category]
            reasons.append(ScoreReason(signal=f"match:{category}", label=label, points=0.0))
        if matched:
            reasons.insert(
                0,
                ScoreReason(
                    signal="keywords",
                    label=f"{len(matched)} of your interests appear in this opportunity",
                    points=points,
                ),
            )
        return points, reasons

    def _field_score(self, opportunity: Opportunity, profile: Profile) -> tuple[float, list[ScoreReason]]:
        preferred = [f for f in (profile.preferred_fields or []) if f]
        if not preferred:
            return 0.0, []
        text = " ".join(
            part for part in (opportunity.field, opportunity.research_area, opportunity.title) if part
        )
        for field in preferred:
            if contains_term(text, field):
                return W_FIELD, [
                    ScoreReason(
                        signal="field",
                        label=f"Field of study aligns with '{field}'",
                        points=W_FIELD,
                    )
                ]
        if opportunity.field:
            return 0.0, [
                ScoreReason(
                    signal="field",
                    label=f"Field '{opportunity.field}' is outside your preferred fields",
                    points=0.0,
                )
            ]
        return 0.0, []

    def _degree_score(self, opportunity: Opportunity, profile: Profile) -> tuple[float, list[ScoreReason]]:
        required = _DEGREE_RANK.get(str(opportunity.degree_level or "").lower(), 0)
        required_text = " ".join(
            part
            for part in (opportunity.required_degree, opportunity.eligibility, opportunity.title)
            if part
        )
        if not required and required_text:
            for marker, rank in (
                ("phd", 3),
                ("doctoral", 3),
                ("doctorate", 3),
                ("master", 2),
                ("bachelor", 1),
                ("undergraduate", 1),
            ):
                if marker in required_text.lower():
                    required = rank
                    break
        mine = _DEGREE_RANK.get(str(profile.degree_level or "").lower(), 2)
        if not required:
            return W_DEGREE * 0.6, [
                ScoreReason(
                    signal="degree",
                    label="No explicit degree barrier stated",
                    points=W_DEGREE * 0.6,
                )
            ]
        if mine >= required:
            return W_DEGREE, [
                ScoreReason(
                    signal="degree",
                    label="Degree requirement satisfied",
                    points=W_DEGREE,
                )
            ]
        penalty = -8.0 if required - mine == 1 else -12.0
        return penalty, [
            ScoreReason(
                signal="degree",
                label=f"Requires a higher degree level than your profile ({(profile.degree_level or 'unspecified')})",
                points=penalty,
            )
        ]

    def _funding_score(self, opportunity: Opportunity, profile: Profile) -> tuple[float, list[ScoreReason]]:
        preference = (profile.funding_preference or "any").lower()
        reasons: list[ScoreReason] = []
        points = 0.0
        if preference in {"any", ""}:
            if opportunity.funding_type in {FundingType.FULL, FundingType.PAID_POSITION}:
                points = W_FUNDING * 0.7
                reasons.append(
                    ScoreReason(
                        signal="funding",
                        label=f"Funded role: {opportunity.funding_type_raw or opportunity.funding_type.value}",
                        points=points,
                    )
                )
            return points, reasons
        wanted = {
            "full": {FundingType.FULL},
            "fully funded": {FundingType.FULL},
            "partial": {FundingType.PARTIAL, FundingType.FULL},
            "paid": {FundingType.PAID_POSITION},
            "self": {FundingType.SELF},
            "self-funded": {FundingType.SELF},
        }.get(preference, set())
        if not wanted:
            return 0.0, reasons
        if opportunity.funding_type in wanted:
            points = W_FUNDING
            reasons.append(
                ScoreReason(
                    signal="funding",
                    label=f"Matches your funding preference ({opportunity.funding_type.value})",
                    points=points,
                )
            )
        elif opportunity.funding_type is FundingType.UNKNOWN:
            points = W_FUNDING * 0.3
            reasons.append(
                ScoreReason(
                    signal="funding",
                    label="Funding not stated by the source (unverified)",
                    points=points,
                )
            )
        else:
            points = -4.0
            reasons.append(
                ScoreReason(
                    signal="funding",
                    label=f"Funding type '{opportunity.funding_type.value}' differs from your preference",
                    points=points,
                )
            )
        if profile.max_tuition is not None and opportunity.tuition:
            if opportunity.tuition > float(profile.max_tuition):
                points -= 6.0
                reasons.append(
                    ScoreReason(
                        signal="tuition",
                        label=(
                            f"Tuition {opportunity.tuition:,.0f} exceeds your maximum "
                            f"{float(profile.max_tuition):,.0f}"
                        ),
                        points=-6.0,
                    )
                )
        if profile.desired_salary and opportunity.salary and opportunity.salary >= float(
            profile.desired_salary
        ):
            points += 2.0
            reasons.append(
                ScoreReason(
                    signal="salary",
                    label="Salary meets or exceeds your target",
                    points=2.0,
                )
            )
        return points, reasons


    def _location_score(self, opportunity: Opportunity, profile: Profile) -> tuple[float, list[ScoreReason]]:
        country = _normalize_country(opportunity.country)
        excluded = {_normalize_country(c) for c in (profile.excluded_countries or [])}
        preferred = {_normalize_country(c) for c in (profile.preferred_countries or [])}
        if country and country in excluded:
            return -25.0, [
                ScoreReason(
                    signal="location",
                    label=f"{opportunity.country} is on your excluded list",
                    points=-25.0,
                )
            ]
        if country and country in preferred:
            return W_LOCATION, [
                ScoreReason(
                    signal="location",
                    label=f"{opportunity.country} is a preferred country",
                    points=W_LOCATION,
                )
            ]
        if opportunity.remote_status == "remote" and profile.remote_preference in {
            "remote",
            "any",
            "",
        }:
            return W_LOCATION * 0.8, [
                ScoreReason(
                    signal="location",
                    label="Remote position (no relocation needed)",
                    points=W_LOCATION * 0.8,
                )
            ]
        if not country:
            return W_LOCATION * 0.3, [
                ScoreReason(
                    signal="location",
                    label="Location not stated by the source",
                    points=W_LOCATION * 0.3,
                )
            ]
        if preferred:
            return W_LOCATION * 0.3, [
                ScoreReason(
                    signal="location",
                    label=f"{opportunity.country} is not on your preferred list",
                    points=W_LOCATION * 0.3,
                )
            ]
        return W_LOCATION * 0.5, []

    def _timeline_score(self, opportunity: Opportunity) -> tuple[float, list[ScoreReason], bool]:
        """Timeline + recency. Third value = hard disqualification."""
        today = datetime.now(UTC).date()
        reasons: list[ScoreReason] = []
        points = 0.0
        deadline = opportunity.deadline
        if deadline:
            days_left = (deadline - today).days
            if days_left < 0:
                return (
                    0.0,
                    [
                        ScoreReason(
                            signal="deadline",
                            label=f"Deadline passed on {deadline.isoformat()}",
                            points=0.0,
                        )
                    ],
                    True,
                )
            if days_left <= 30:
                points += W_TIMELINE
                reasons.append(
                    ScoreReason(
                        signal="deadline",
                        label=f"Deadline still open — closes in {days_left} day(s)",
                        points=W_TIMELINE,
                    )
                )
            else:
                points += W_TIMELINE * 0.6
                reasons.append(
                    ScoreReason(
                        signal="deadline",
                        label=f"Deadline {deadline.isoformat()} ({days_left} days left)",
                        points=W_TIMELINE * 0.6,
                    )
                )
        else:
            points += W_TIMELINE * 0.4
            reasons.append(
                ScoreReason(
                    signal="deadline",
                    label="Rolling / no fixed deadline",
                    points=W_TIMELINE * 0.4,
                )
            )
        discovered = opportunity.discovered_at
        if discovered:
            discovered_date = discovered.date() if isinstance(discovered, datetime) else discovered
            if (today - discovered_date).days <= 7:
                points += 2.0
                reasons.append(
                    ScoreReason(signal="recency", label="Discovered this week", points=2.0)
                )
        return points, reasons, False


    def _constraint_penalties(self, opportunity: Opportunity, profile: Profile) -> list[ScoreReason]:
        reasons: list[ScoreReason] = []
        text = self._haystack(opportunity).lower()
        for keyword in profile.excluded_keywords or []:
            if keyword and contains_term(text, keyword):
                reasons.append(
                    ScoreReason(
                        signal="excluded_keyword",
                        label=f"Contains excluded keyword '{keyword}'",
                        points=-10.0,
                    )
                )
        if profile.ielts_score is not None and opportunity.ielts_requirement:
            required = _first_number(opportunity.ielts_requirement)
            if required is not None and float(profile.ielts_score) < required:
                reasons.append(
                    ScoreReason(
                        signal="language",
                        label=(
                            f"IELTS {required:g} required; your profile lists "
                            f"{profile.ielts_score:g}"
                        ),
                        points=-6.0,
                    )
                )
        if profile.toefl_score is not None and opportunity.toefl_requirement:
            required = _first_number(opportunity.toefl_requirement)
            if required is not None and float(profile.toefl_score) < required:
                reasons.append(
                    ScoreReason(
                        signal="language",
                        label=(
                            f"TOEFL {required:g} required; your profile lists "
                            f"{profile.toefl_score:g}"
                        ),
                        points=-6.0,
                    )
                )
        restriction = opportunity.citizenship_restrictions
        if restriction and profile.nationality:
            if _restricts_citizenship(restriction) and not contains_term(
                restriction, profile.nationality
            ):
                reasons.append(
                    ScoreReason(
                        signal="citizenship",
                        label=f"Citizenship restriction: {restriction}",
                        points=-8.0,
                    )
                )
        if opportunity.experience_requirement and profile.years_experience is not None:
            required_years = _first_number(opportunity.experience_requirement)
            if required_years is not None and float(profile.years_experience) < required_years:
                reasons.append(
                    ScoreReason(
                        signal="experience",
                        label=f"{required_years:g}+ years of experience requested",
                        points=-5.0,
                    )
                )
        return reasons

    # -- public API -----------------------------------------------------
    def score(self, opportunity: Opportunity, profile: Profile) -> ScoreResult:
        """Score an opportunity 0-100 with a full explanation."""
        matched = self._match_terms(opportunity, profile)
        keyword_points, reasons = self._keyword_score(matched, profile)
        field_points, field_reasons = self._field_score(opportunity, profile)
        degree_points, degree_reasons = self._degree_score(opportunity, profile)
        funding_points, funding_reasons = self._funding_score(opportunity, profile)
        location_points, location_reasons = self._location_score(opportunity, profile)
        timeline_points, timeline_reasons, expired = self._timeline_score(opportunity)
        penalty_reasons = self._constraint_penalties(opportunity, profile)

        all_reasons = [
            *reasons,
            *field_reasons,
            *degree_reasons,
            *funding_reasons,
            *location_reasons,
            *timeline_reasons,
            *penalty_reasons,
        ]
        raw = (
            keyword_points
            + field_points
            + degree_points
            + funding_points
            + location_points
            + timeline_points
            + sum(r.points for r in penalty_reasons)
        )
        score = max(0.0, min(100.0, raw))
        if expired:
            return ScoreResult(score=min(score, 15.0), reasons=all_reasons, disqualified=True)
        return ScoreResult(score=round(score, 1), reasons=all_reasons)


def _first_number(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def _restricts_citizenship(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "only",
            "must be",
            "citizens",
            "nationals",
            "permanent resident",
            "restricted",
            "requires",
        )
    )


__all__ = [
    "LexicalRankingStrategy",
    "W_DEGREE",
    "W_FIELD",
    "W_FUNDING",
    "W_KEYWORDS",
    "W_LOCATION",
    "W_TIMELINE",
]

