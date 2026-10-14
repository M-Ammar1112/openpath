"""Ingestion pipeline: source -> fetch -> parse -> normalize -> validate -> DB.

Design notes:
  * One connector failure never aborts a refresh run (isolation per source).
  * Every attempt writes a `SourceFetch` audit row with counters and error.
  * Provenance is preserved through `upsert_opportunity` (see services/dedup).
  * New/updated rows are scored immediately so the UI never shows stale scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import FetchContext, NormalizedOpportunity
from app.connectors.registry import UnknownConnectorTypeError, build_connector
from app.core.http import FetchBlockedError, FetchError
from app.enums import FreshnessStatus, SourceStatus
from app.logging_config import get_logger
from app.persistence.models import Opportunity, Source, SourceFetch
from app.services.dedup import UpsertOutcome, upsert_opportunity
from app.services.scoring import build_strategy, get_profile, score_opportunity
from app.services.taxonomy import merged_skills

log = get_logger("openpath.services.ingest")


@dataclass(slots=True)
class SourceRunResult:
    source_key: str
    status: str  # ok | error | skipped
    fetched: int = 0
    parsed: int = 0
    new: int = 0
    updated: int = 0
    duplicates: int = 0
    invalid: int = 0
    error: str | None = None
    duration_ms: int = 0
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_key": self.source_key,
            "status": self.status,
            "fetched": self.fetched,
            "parsed": self.parsed,
            "new": self.new,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "messages": self.messages,
        }


def _connector_options(source: Source) -> dict[str, object]:
    """Per-source options from `config/sources.yaml` plus live taxonomy skills."""
    options: dict[str, object] = dict(source.options or {})
    options["skills"] = merged_skills()
    options.setdefault("source_key", source.key)
    return options


async def run_source(session: Session, source: Source, *, score: bool = True) -> SourceRunResult:
    """Run one source end-to-end. Never raises for connector-level failures."""
    started = datetime.now(UTC)
    audit = SourceFetch(source_id=source.id, status="running")
    session.add(audit)
    session.flush()
    result = SourceRunResult(source_key=source.key, status="ok")

    if not source.enabled:
        result.status = "skipped"
        result.messages.append("source disabled")
        _finish(session, source, audit, result, started)
        return result

    source.status = SourceStatus.RUNNING
    try:
        connector = build_connector(
            source.connector_type,
            endpoint_url=source.endpoint_url,
            options=_connector_options(source),
        )
        ctx = FetchContext(
            endpoint_url=source.endpoint_url,
            source_key=source.key,
            rate_limit_seconds=source.rate_limit_seconds,
        )
        records = await connector.fetch(ctx)
        result.fetched = len(records)
        for record in records:
            items = connector.parse(record)
            result.parsed += len(items)
            for item in items:
                try:
                    candidate = _finalize_candidate(connector, item, source)
                except Exception as exc:  # noqa: BLE001 - malformed source row
                    result.invalid += 1
                    result.messages.append(f"normalize failed: {exc}")
                    log.warning(
                        "candidate_normalize_failed",
                        extra={"source": source.key, "error": str(exc)},
                    )
                    continue
                errors = connector.validate(candidate)
                if errors:
                    result.invalid += 1
                    result.messages.append(f"invalid candidate: {'; '.join(errors)}")
                    continue
                outcome = upsert_opportunity(session, candidate, source=source)
                _count_outcome(result, outcome)
                if outcome.outcome == "new":
                    outcome.opportunity.freshness_status = FreshnessStatus.DISCOVERED
                elif outcome.outcome == "updated":
                    outcome.opportunity.freshness_status = FreshnessStatus.UPDATED
                if score and outcome.outcome != "duplicate":
                    _score_one(session, outcome.opportunity)
    except FetchBlockedError as exc:
        result.status = "error"
        result.error = f"blocked by robots.txt: {exc}"
        log.warning("source_blocked", extra={"source": source.key, "error": str(exc)})
    except UnknownConnectorTypeError as exc:
        result.status = "error"
        result.error = str(exc)
        log.error("unknown_connector_type", extra={"source": source.key, "error": str(exc)})
    except FetchError as exc:
        result.status = "error"
        result.error = str(exc)
        log.warning("source_fetch_failed", extra={"source": source.key, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - isolation is the point
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
        log.exception("source_run_failed", extra={"source": source.key})
    finally:
        _finish(session, source, audit, result, started)
    return result


async def run_all_sources(
    session: Session,
    *,
    only_keys: list[str] | None = None,
    score: bool = True,
) -> list[SourceRunResult]:
    """Refresh every enabled source; failures stay isolated per source."""
    query = select(Source).order_by(Source.id)
    if only_keys:
        query = query.where(Source.key.in_(only_keys))
    else:
        query = query.where(Source.enabled.is_(True))
    sources = list(session.execute(query).scalars())
    run_started = datetime.now(UTC)
    results: list[SourceRunResult] = []
    for source in sources:
        results.append(await run_source(session, source, score=score))
    verified = _verify_touched(session, run_started)
    session.commit()
    log.info(
        "refresh_run_completed",
        extra={
            "sources": len(results),
            "new": sum(r.new for r in results),
            "updated": sum(r.updated for r in results),
            "verified": verified,
            "errors": sum(1 for r in results if r.status == "error"),
        },
    )
    return results


def _verify_touched(session: Session, run_started: datetime) -> int:
    """Rows touched in this run move from discovered/updated to verified."""
    rows = list(
        session.execute(
            select(Opportunity).where(
                Opportunity.freshness_status.in_(
                    [FreshnessStatus.DISCOVERED, FreshnessStatus.UPDATED]
                ),
                Opportunity.last_verified_at >= run_started,
            )
        ).scalars()
    )
    return mark_freshness_verified(session, rows)


def _finalize_candidate(connector: object, item: object, source: Source) -> NormalizedOpportunity:
    """Normalize then stamp the source identity onto the candidate."""
    candidate = connector.normalize(item)  # type: ignore[attr-defined]
    candidate.source_key = source.key
    candidate.source_name = source.name
    return candidate


def _count_outcome(result: SourceRunResult, outcome: UpsertOutcome) -> None:
    if outcome.outcome == "new":
        result.new += 1
    elif outcome.outcome == "updated":
        result.updated += 1
    else:
        result.duplicates += 1


def _score_one(session: Session, opportunity: Opportunity) -> None:
    profile = get_profile(session)
    strategy = build_strategy(session)
    score_opportunity(opportunity, profile, strategy)


def _finish(
    session: Session,
    source: Source,
    audit: SourceFetch,
    result: SourceRunResult,
    started: datetime,
) -> None:
    """Close out the audit row and the source status."""
    finished = datetime.now(UTC)
    result.duration_ms = int((finished - started).total_seconds() * 1000)
    audit.finished_at = finished
    audit.status = result.status
    audit.records_fetched = result.fetched
    audit.records_new = result.new
    audit.records_updated = result.updated
    audit.records_duplicate = result.duplicates
    audit.records_invalid = result.invalid
    audit.error = result.error
    audit.duration_ms = result.duration_ms

    source.last_fetched_at = finished
    source.last_error = result.error
    if result.status == "error":
        source.status = SourceStatus.ERROR
    elif result.status == "skipped":
        source.status = SourceStatus.DISABLED
    else:
        source.status = SourceStatus.OK
    session.flush()


def mark_freshness_verified(session: Session, opportunities: list[Opportunity]) -> int:
    """Promote discovered/updated rows to VERIFIED after a successful refresh."""
    count = 0
    for row in opportunities:
        if row.freshness_status in {FreshnessStatus.DISCOVERED, FreshnessStatus.UPDATED}:
            row.freshness_status = FreshnessStatus.VERIFIED
            count += 1
    session.flush()
    return count


__all__ = [
    "SourceRunResult",
    "mark_freshness_verified",
    "run_all_sources",
    "run_source",
]

