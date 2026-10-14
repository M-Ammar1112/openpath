"""Taxonomy loading and seeding.

Taxonomy lives in YAML files under `app/taxonomy/`, which keeps the
platform field-agnostic: swapping taxonomy + profile retargets OpenPath to
another domain without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import TaxonomyKind
from app.logging_config import get_logger
from app.persistence.models import TaxonomyTerm

log = get_logger("openpath.services.taxonomy")

TAXONOMY_DIR = Path(__file__).resolve().parents[1] / "taxonomy"


@dataclass(slots=True)
class TaxonomySeed:
    name: str
    fields: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    synonyms: dict[str, list[str]] = field(default_factory=dict)
    preferred_countries: list[str] = field(default_factory=list)


@lru_cache
def load_taxonomy_files(directory: str | None = None) -> tuple[TaxonomySeed, ...]:
    """Load and cache every taxonomy YAML file in the taxonomy directory."""
    path = Path(directory) if directory else TAXONOMY_DIR
    seeds: list[TaxonomySeed] = []
    if not path.exists():
        log.warning("taxonomy_dir_missing", extra={"path": str(path)})
        return ()
    for file in sorted(path.glob("*.yaml")):
        try:
            data: Any = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            log.error("taxonomy_load_failed", extra={"file": str(file), "error": str(exc)})
            continue
        if not isinstance(data, dict):
            continue
        synonyms: dict[str, list[str]] = {}
        for group in data.get("synonyms") or []:
            if isinstance(group, dict) and group.get("canonical"):
                terms = [str(t) for t in (group.get("terms") or []) if t]
                synonyms[str(group["canonical"])] = terms
        seeds.append(
            TaxonomySeed(
                name=str(data.get("name") or file.stem),
                fields=[str(x) for x in (data.get("fields") or [])],
                skills=[str(x) for x in (data.get("skills") or [])],
                synonyms=synonyms,
                preferred_countries=[str(x) for x in (data.get("preferred_countries") or [])],
            )
        )
    return tuple(seeds)


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = str(value).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(value))
    return out


def merged_skills(seeds: tuple[TaxonomySeed, ...] | None = None) -> list[str]:
    source = seeds if seeds is not None else load_taxonomy_files()
    return _dedupe(skill for seed in source for skill in seed.skills)


def merged_fields(seeds: tuple[TaxonomySeed, ...] | None = None) -> list[str]:
    source = seeds if seeds is not None else load_taxonomy_files()
    return _dedupe(term for seed in source for term in seed.fields)


def merged_synonyms(seeds: tuple[TaxonomySeed, ...] | None = None) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for seed in seeds or load_taxonomy_files():
        for canonical, terms in seed.synonyms.items():
            existing = merged.setdefault(canonical, [])
            for term in terms:
                if term not in existing:
                    existing.append(term)
    return merged


def merged_preferred_countries(seeds: tuple[TaxonomySeed, ...] | None = None) -> list[str]:
    source = seeds if seeds is not None else load_taxonomy_files()
    return _dedupe(term for seed in source for term in seed.preferred_countries)


def sync_taxonomy(session: Session, seeds: tuple[TaxonomySeed, ...] | None = None) -> int:
    """Insert any taxonomy terms not yet present. Returns rows added."""
    source = seeds if seeds is not None else load_taxonomy_files()
    existing = {
        (kind, term)
        for kind, term in session.execute(select(TaxonomyTerm.kind, TaxonomyTerm.term)).all()
    }
    added = 0
    for seed in source:
        for term in seed.fields:
            added += _add(session, existing, TaxonomyKind.FIELD, term, group=seed.name)
        for term in seed.skills:
            added += _add(session, existing, TaxonomyKind.SKILL, term, group=seed.name)
        for canonical, terms in seed.synonyms.items():
            added += _add(session, existing, TaxonomyKind.SYNONYM, canonical, group=seed.name)
            for term in terms:
                added += _add(
                    session,
                    existing,
                    TaxonomyKind.SYNONYM,
                    term,
                    group=seed.name,
                    canonical=canonical,
                )
        for country in seed.preferred_countries:
            added += _add(session, existing, TaxonomyKind.COUNTRY, country, group=seed.name)
    if added:
        log.info("taxonomy_synced", extra={"added": added})
    return added


def _add(
    session: Session,
    existing: set[tuple[TaxonomyKind, str]],
    kind: TaxonomyKind,
    term: str,
    *,
    group: str | None = None,
    canonical: str | None = None,
) -> int:
    key = (kind, term)
    if key in existing:
        return 0
    session.add(TaxonomyTerm(kind=kind, term=term, group=group, canonical=canonical))
    existing.add(key)
    return 1


def terms_by_kind(session: Session, kind: TaxonomyKind) -> list[TaxonomyTerm]:
    return list(
        session.execute(
            select(TaxonomyTerm).where(TaxonomyTerm.kind == kind).order_by(TaxonomyTerm.term)
        ).scalars()
    )


def synonym_map(session: Session) -> dict[str, list[str]]:
    """Build canonical -> [variants] from the database (fallback: YAML)."""
    mapping: dict[str, list[str]] = {}
    for row in terms_by_kind(session, TaxonomyKind.SYNONYM):
        if row.canonical:
            mapping.setdefault(row.canonical, []).append(row.term)
        else:
            mapping.setdefault(row.term, [])
    return mapping or merged_synonyms()


__all__ = [
    "TAXONOMY_DIR",
    "TaxonomySeed",
    "load_taxonomy_files",
    "merged_fields",
    "merged_preferred_countries",
    "merged_skills",
    "merged_synonyms",
    "sync_taxonomy",
    "synonym_map",
    "terms_by_kind",
]

