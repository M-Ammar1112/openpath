"""Field-level normalization: funding, degree levels, dates, types, skills.

Rule: never infer critical facts. "Fully funded" is only assigned when the
source text provides explicit evidence; otherwise the value stays
`partial`/`unknown` and the original text is preserved by the caller.
"""

from __future__ import annotations

import re
from datetime import date

from dateutil import parser as dateparser

from app.enums import DegreeLevel, FundingType, OpportunityType
from app.normalize.text import contains_term, tokenize

# --- funding ---------------------------------------------------------------

_FULL_PATTERNS = (
    "fully funded",
    "full funding",
    "full scholarship",
    "100% scholarship",
    "full tuition and living",
    "covers tuition and living",
    "tuition and stipend covered",
    "fully financed",
    "fully-funded",
)
_PARTIAL_PATTERNS = (
    "partial",
    "tuition waiver",
    "tuition discount",
    "reduced tuition",
    "merit scholarship",
    "need-based aid",
    "stipend only",
    "25%",
    "50%",
    "75%",
)
_SELF_PATTERNS = ("self-funded", "self funded", "self financing", "tuition only", "fully self")
_PAID_PATTERNS = (
    "salary",
    "stipend",
    "paid position",
    "remuneration",
    "graduate assistantship",
    "research assistant",
    "teaching assistant",
    "postdoc",
)


def normalize_funding(text: str | None, *, has_salary: bool = False) -> FundingType:
    """Map source wording to a funding category — explicit evidence for FULL."""
    if not text:
        return FundingType.PAID_POSITION if has_salary else FundingType.UNKNOWN
    lowered = text.lower()
    if any(p in lowered for p in _FULL_PATTERNS):
        return FundingType.FULL
    if any(p in lowered for p in _SELF_PATTERNS):
        return FundingType.SELF
    if any(p in lowered for p in _PARTIAL_PATTERNS):
        return FundingType.PARTIAL
    if has_salary or any(p in lowered for p in _PAID_PATTERNS):
        return FundingType.PAID_POSITION
    if contains_term(lowered, "funded") or contains_term(lowered, "scholarship"):
        # Vague wording without coverage details → at most partial
        return FundingType.PARTIAL
    return FundingType.UNKNOWN


# --- degree levels ---------------------------------------------------------


def normalize_degree_level(text: str | None) -> DegreeLevel:
    """Map "Ph.D.", "PhD", "Doctoral", "Master's", "MSc" … to DegreeLevel."""
    if not text:
        return DegreeLevel.UNKNOWN
    lowered = text.lower()
    squashed = re.sub(r"[^a-z0-9]+", "", lowered)
    if any(
        marker in squashed
        for marker in ("phd", "phdprogram", "doctoral", "doctorate", "dphil")
    ):
        return DegreeLevel.DOCTORATE
    if any(
        marker in squashed
        for marker in ("master", "msc", "meng", "mtech", "mba", "graduateprogram")
    ):
        return DegreeLevel.MASTERS
    if any(
        marker in squashed
        for marker in ("bachelor", "bsc", "ba", "undergraduate", "beng")
    ):
        return DegreeLevel.BACHELORS
    if any(marker in lowered for marker in ("no degree", "none", "high school")):
        return DegreeLevel.NONE
    if "any" in lowered.split():
        return DegreeLevel.ANY
    return DegreeLevel.UNKNOWN


# --- dates -----------------------------------------------------------------

_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%d %B %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%b %d, %Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d.%m.%Y",
)


def parse_date(value: str | None) -> date | None:
    """Parse a deadline/opening date conservatively; None when unsure."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_PATTERNS:
        try:
            return date.fromisoformat(text) if fmt == "%Y-%m-%d" else _strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = dateparser.parse(text, fuzzy=True, dayfirst=False)
    except (ValueError, OverflowError):
        return None
    return parsed.date() if parsed else None


def _strptime(text: str, fmt: str) -> date:
    from datetime import datetime

    return datetime.strptime(text, fmt).date()


# --- opportunity types -----------------------------------------------------

_TYPE_RULES: tuple[tuple[OpportunityType, tuple[str, ...]], ...] = (
    (OpportunityType.SCHOLARSHIP, ("scholarship", "grant", "financial aid")),
    (OpportunityType.FELLOWSHIP, ("fellowship", "fellow ", "scholar program")),
    (OpportunityType.PHD_PROGRAM, ("phd", "doctoral", "ph d")),
    (OpportunityType.MASTERS_PROGRAM, ("master", "msc", "meng", "mtech", "mba")),
    (OpportunityType.GRADUATE_ASSISTANTSHIP, ("graduate assistant", "teaching assistant", "ta position")),
    (OpportunityType.RESEARCH_POSITION, ("research assistant", "research associate", "postdoc", "researcher", "research position", "research fellow")),
    (OpportunityType.INTERNSHIP, ("intern", "internship", "co-op", "coop")),
    (OpportunityType.ACADEMIC_JOB, ("faculty", "professor", "lecturer", "assistant professor", "associate professor", "adjunct")),
    (OpportunityType.INDUSTRY_JOB, ("engineer", "developer", "job opening", "vacancy", "position", "hiring")),
    (OpportunityType.FUNDED_PROGRAM, ("funded program", "fully funded", "phd position", "grad program")),
)


def infer_opportunity_type(text: str | None, *, default: OpportunityType = OpportunityType.OTHER) -> OpportunityType:
    """Best-effort classification from free text; order matters (specific first)."""
    if not text:
        return default
    lowered = text.lower()
    for kind, markers in _TYPE_RULES:
        if any(marker in lowered for marker in markers):
            return kind
    return default


# --- skills ----------------------------------------------------------------


def extract_skills(text: str | None, vocabulary: list[str]) -> list[str]:
    """Return vocabulary terms present in `text` (case-insensitive)."""
    if not text or not vocabulary:
        return []
    haystack = tokenize(text, drop_stopwords=False)
    found: list[str] = []
    lowered_text = text.lower()
    for term in vocabulary:
        term_tokens = tokenize(term, drop_stopwords=False)
        if term_tokens and term_tokens <= haystack:
            found.append(term)
        elif contains_term(lowered_text, term):
            found.append(term)
    return found


__all__ = [
    "extract_skills",
    "infer_opportunity_type",
    "normalize_degree_level",
    "normalize_funding",
    "parse_date",
]