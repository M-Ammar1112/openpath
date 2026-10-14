"""Idempotent seeding of the default profile, taxonomy, and sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.enums import SourceCategory, SourceStatus
from app.logging_config import get_logger
from app.persistence.models import Profile, Source
from app.services.taxonomy import (
    load_taxonomy_files,
    merged_fields,
    merged_preferred_countries,
    merged_skills,
    sync_taxonomy,
)

log = get_logger("openpath.services.seed")

SOURCES_FILE = REPO_ROOT / "config" / "sources.yaml"

# Seeded ECE/hardware profile. Every value is editable from the Profile page.
DEFAULT_PROFILE: dict[str, Any] = {
    "display_name": "ECE / RTL candidate",
    "preferred_fields": [
        "Digital IC Design",
        "ASIC Design",
        "FPGA Design",
        "SoC Design",
        "Hardware Verification",
        "Computer Architecture",
        "VLSI",
        "Embedded Systems",
        "EDA",
    ],
    "skills": [
        "RTL Design",
        "RTL Verification",
        "Verilog",
        "SystemVerilog",
        "UVM",
        "Formal Verification",
        "SVA",
        "Assertions",
        "SystemC",
        "TLM",
        "C++",
        "Hardware Modeling",
        "Python",
        "Computer Architecture",
        "STA",
        "Synthesis",
        "CDC",
        "Lint",
    ],
    "research_interests": [
        "RTL verification",
        "formal verification",
        "hardware modeling",
        "performance modeling",
        "processor microarchitecture",
        "ASIC design",
    ],
    "preferred_keywords": [
        "RTL",
        "SystemVerilog",
        "UVM",
        "ASIC",
        "FPGA",
        "SoC",
        "verification",
        "digital design",
        "SystemC",
        "C++",
    ],
    "excluded_keywords": [],
    "degrees": ["BSc Electrical Engineering"],
    "degree_level": "bachelors",
    "years_experience": 1.0,
    "desired_program_types": ["phd_program", "masters_program", "funded_program"],
    "desired_job_types": ["industry_job", "research_position", "internship"],
    "funding_preference": "any",
    "willingness_to_relocate": True,
    "remote_preference": "any",
    "languages": ["English", "Urdu"],
}


def seed_profile(session: Session, *, preferred_countries: list[str] | None = None) -> Profile:
    """Create the single default profile if none exists (never overwrites)."""
    existing = session.execute(select(Profile).order_by(Profile.id).limit(1)).scalar_one_or_none()
    if existing is not None:
        return existing
    data = dict(DEFAULT_PROFILE)
    countries = preferred_countries or merged_preferred_countries() or ["Germany", "Netherlands"]
    profile = Profile(preferred_countries=countries, **data)
    session.add(profile)
    session.flush()
    log.info("profile_seeded", extra={"profile_id": profile.id})
    return profile


def load_source_definitions(path: Path | None = None) -> list[dict[str, Any]]:
    """Read `config/sources.yaml` (returns [] with a warning if missing)."""
    file = path or SOURCES_FILE
    if not file.exists():
        log.warning("sources_file_missing", extra={"path": str(file)})
        return []
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.error("sources_file_invalid", extra={"path": str(file), "error": str(exc)})
        return []
    sources = data.get("sources") if isinstance(data, dict) else None
    return [s for s in (sources or []) if isinstance(s, dict) and s.get("key")]


def seed_sources(session: Session, path: Path | None = None) -> tuple[int, int]:
    """Create sources from YAML. Returns (created, already_present)."""
    created = 0
    existing = 0
    for definition in load_source_definitions(path):
        key = str(definition["key"])
        found = session.execute(select(Source).where(Source.key == key)).scalar_one_or_none()
        if found is not None:
            existing += 1
            continue
        try:
            category = SourceCategory(str(definition.get("category", "manual")))
        except ValueError:
            category = SourceCategory.MANUAL
        enabled = bool(definition.get("enabled", True))
        session.add(
            Source(
                key=key,
                name=str(definition.get("name") or key),
                category=category,
                connector_type=str(definition.get("connector_type") or "rss"),
                endpoint_url=definition.get("endpoint_url"),
                description=definition.get("description"),
                license_notes=definition.get("license_notes"),
                enabled=enabled,
                fetch_interval_seconds=int(definition.get("fetch_interval_seconds", 3600)),
                rate_limit_seconds=float(definition.get("rate_limit_seconds", 2.0)),
                options=dict(definition.get("options") or {}),
                status=SourceStatus.IDLE if enabled else SourceStatus.DISABLED,
            )
        )
        created += 1
    if created:
        log.info("sources_seeded", extra={"created": created, "existing": existing})
    return created, existing


def seed_all(session: Session) -> dict[str, int]:
    """Seed taxonomy, profile, and sources in one idempotent call."""
    taxonomy_added = sync_taxonomy(session, load_taxonomy_files())
    profile = seed_profile(session, preferred_countries=merged_preferred_countries())
    created, existing = seed_sources(session)
    source_count = session.execute(select(func.count()).select_from(Source)).scalar_one()
    session.flush()
    return {
        "taxonomy_terms_added": taxonomy_added,
        "taxonomy_skills": len(merged_skills()),
        "taxonomy_fields": len(merged_fields()),
        "profile_id": int(profile.id),
        "sources_created": created,
        "sources_existing": existing,
        "sources_total": int(source_count),
    }


__all__ = [
    "DEFAULT_PROFILE",
    "SOURCES_FILE",
    "load_source_definitions",
    "seed_all",
    "seed_profile",
    "seed_sources",
]

