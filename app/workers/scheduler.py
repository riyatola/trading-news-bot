"""Background job scheduling (APScheduler + Redis job store target for v1).

Sprint 2 registers:
- Hourly asset universe sync (app.workers.asset_sync.sync_assets)
- Quarterly asset-relationship review reminder (manual review; see README
  risk mitigation #1 -- auto-discovery of relationships is deferred to v2)

Later sprints add: market ingestion (seconds), news/X polling (1-5 min),
event processing (5 min), opportunity recalculation (15 min), daily
briefing, weekly credibility recalculation (deferred), monthly signal
performance analysis.
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.db.database import SessionLocal
from app.market.mexc import MEXCClient
from app.workers.asset_sync import sync_assets

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_asset_sync_job() -> None:
    """Job wrapper: open a DB session, run sync, always close the session."""
    db = SessionLocal()
    try:
        result = await sync_assets(db)
        if not result.ok:
            logger.error("Scheduled asset sync failed: %s", result.error)
    except Exception:
        logger.exception("Unhandled error in scheduled asset sync job")
    finally:
        db.close()


def quarterly_relationship_review_reminder() -> None:
    """Placeholder job: logs a reminder that asset_relationships is due for
    manual quarterly review (per README risk mitigation strategy #1).
    Does not modify any data -- the actual review is a manual/analyst task.
    """
    logger.info(
        "Quarterly asset_relationships review is due. "
        "Review 10-K competitive/risk sections and sector maps for drift."
    )


def create_scheduler() -> AsyncIOScheduler:
    """Build (but do not start) the application scheduler with all jobs
    registered."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        run_asset_sync_job,
        trigger=IntervalTrigger(hours=1),
        id="asset_sync_hourly",
        name="Hourly MEXC asset universe sync",
        replace_existing=True,
        next_run_time=None,  # first run scheduled by the interval, not immediately
    )

    scheduler.add_job(
        quarterly_relationship_review_reminder,
        trigger=CronTrigger(month="1,4,7,10", day=1, hour=9),
        id="relationship_review_quarterly",
        name="Quarterly asset relationship review reminder",
        replace_existing=True,
    )

    return scheduler


def start_scheduler() -> AsyncIOScheduler:
    """Start the global scheduler singleton (idempotent)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = create_scheduler()
    if not _scheduler.running:
        _scheduler.start()
        logger.info("Background job scheduler started")
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Background job scheduler stopped")
