"""Background jobs (APScheduler, in-process).

Rationale (docs/ARCHITECTURE.md AD-5): job volume is low (minute/hour
intervals for a single local user) so a broker such as Redis/Celery would
add operational weight without benefit. Every job opens its own session,
logs structured events, and never raises into the scheduler.
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.logging_config import get_logger
from app.persistence.db import get_session_factory
from app.services.analytics import dashboard_summary
from app.services.freshness import archive_long_expired, sweep_freshness
from app.services.ingest import run_all_sources
from app.services.watchlists import check_watchlists

log = get_logger("openpath.jobs")

_scheduler: AsyncIOScheduler | None = None


async def job_refresh_sources() -> None:
    """Fetch every enabled source, isolate failures, then re-score."""
    factory = get_session_factory()
    with factory() as session:
        try:
            results = await run_all_sources(session)
            summary = dashboard_summary(session)
        except Exception:  # noqa: BLE001 - jobs must not kill the scheduler
            session.rollback()
            log.exception("job_refresh_sources_failed")
            return
    log.info(
        "job_refresh_sources_done",
        extra={
            "sources": len(results),
            "new": sum(r.new for r in results),
            "opportunities": summary["totals"]["opportunities"],
        },
    )


def job_freshness_sweep() -> None:
    """Mark expired/stale rows and archive long-expired ones."""
    factory = get_session_factory()
    with factory() as session:
        try:
            counts = sweep_freshness(session)
            archived = archive_long_expired(session)
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            log.exception("job_freshness_sweep_failed")
            return
    log.info("job_freshness_sweep_done", extra={**counts, "archived": archived})


def job_watchlist_check() -> None:
    """Turn new matches into dashboard notifications."""
    factory = get_session_factory()
    with factory() as session:
        try:
            created = check_watchlists(session)
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            log.exception("job_watchlist_check_failed")
            return
    log.info("job_watchlist_check_done", extra={"notifications": created})


def job_cache_cleanup(max_age_hours: float = 168.0) -> None:
    """Delete stale response-cache files (keeps the data dir small)."""
    import time

    cache_dir = settings.data_dir / "cache"
    if not cache_dir.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for file in cache_dir.glob("*.json"):
        try:
            if file.stat().st_mtime < cutoff:
                file.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        log.info("job_cache_cleanup_done", extra={"removed": removed})


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        job_refresh_sources,
        trigger=IntervalTrigger(seconds=settings.refresh_interval_seconds),
        id="refresh_sources",
        name="Refresh all enabled sources",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        job_freshness_sweep,
        trigger=IntervalTrigger(seconds=settings.freshness_sweep_interval_seconds),
        id="freshness_sweep",
        name="Sweep freshness statuses",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        job_watchlist_check,
        trigger=IntervalTrigger(seconds=settings.watchlist_check_interval_seconds),
        id="watchlist_check",
        name="Check watchlists",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        job_cache_cleanup,
        trigger=IntervalTrigger(hours=24),
        id="cache_cleanup",
        name="Clean response cache",
        max_instances=1,
        replace_existing=True,
    )
    return scheduler


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the scheduler unless disabled by configuration."""
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("scheduler_disabled")
        return None
    if _scheduler is not None:
        return _scheduler
    _scheduler = build_scheduler()
    _scheduler.start()
    log.info(
        "scheduler_started",
        extra={
            "jobs": [job.id for job in _scheduler.get_jobs()],
            "refresh_interval_seconds": settings.refresh_interval_seconds,
        },
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("scheduler_stopped")


def run_refresh_once() -> list[dict[str, object]]:
    """Synchronous helper for scripts/CLI (runs one refresh cycle)."""
    return asyncio.run(_refresh_once_async())


async def _refresh_once_async() -> list[dict[str, object]]:
    factory = get_session_factory()
    with factory() as session:
        results = await run_all_sources(session)
        return [result.as_dict() for result in results]


__all__ = [
    "build_scheduler",
    "job_cache_cleanup",
    "job_freshness_sweep",
    "job_refresh_sources",
    "job_watchlist_check",
    "run_refresh_once",
    "shutdown_scheduler",
    "start_scheduler",
]
