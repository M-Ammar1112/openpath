"""Ranking contracts: explainable scores with human-readable reasons."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.persistence.models import Opportunity, Profile


@dataclass(slots=True)
class ScoreReason:
    """One contribution to a relevance score."""

    signal: str  # e.g. "keyword", "location", "deadline"
    label: str  # human-readable sentence, e.g. "SystemVerilog mentioned"
    points: float  # positive (bonus) or negative (penalty)

    def as_dict(self) -> dict[str, object]:
        return {"signal": self.signal, "label": self.label, "points": round(self.points, 2)}


@dataclass(slots=True)
class ScoreResult:
    """Final score plus the explanation breakdown."""

    score: float
    reasons: list[ScoreReason] = field(default_factory=list)
    disqualified: bool = False

    def to_payload(self) -> list[dict[str, object]]:
        ordered = sorted(self.reasons, key=lambda r: abs(r.points), reverse=True)
        return [reason.as_dict() for reason in ordered]


class RankingStrategy(Protocol):
    """Scoring strategy interface.

    The default implementation is deterministic and lexical. A future
    embeddings/LLM strategy can implement the same method without touching
    callers (see docs/ARCHITECTURE.md AD-6).
    """

    name: str

    def score(self, opportunity: Opportunity, profile: Profile) -> ScoreResult: ...


__all__ = ["RankingStrategy", "ScoreReason", "ScoreResult"]
