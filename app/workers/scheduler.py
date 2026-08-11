"""Background job scheduling (APScheduler + Redis job store target for v1).

Sprint 2 registers:
- Hourly asset universe sync (app.workers.asset_sync.sync_assets)
- Quarterly asset-relationship review reminder (manual review; see README
  risk mitigation #1 -- auto-discovery of relationships is deferred to v2)

Sprint 4 adds news/SEC/company-IR polling (and, from Sprint 7, X --
folded into the same adapter set, see app.workers.news_ingestion).
Sprint 5 adds AI event processing. Sprint 6 adds Telegram alert dispatch
and the daily briefing. Sprint 8 will add opportunity recalculation
(every 15 min) and weekly credibility recalculation (deferred).
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.db.database import SessionLocal
from app.market.mexc import MEXCClient
from app.workers.alerts import run_alert_dispatch_poll
from app.workers.asset_sync import sync_assets
from app.workers.briefing import run_daily_briefing_job as generate_daily_briefing
from app.workers.event_processing import run_event_processing_poll
from app.workers.news_ingestion import run_news_ingestion_poll

logger = logging.getLogger(__name__)

# News/SEC/company-IR/X polling cadence (Sprint 4, extended by Sprint 7).
# 3 minutes sits in the spec's "every 1-5 minutes" band; SEC EDGAR issues
# one request per tracked company per poll (no batched query support
# there), so this also keeps EDGAR call volume reasonable across a
# 52-asset universe.
NEWS_INGESTION_INTERVAL_MINUTES = 3

# AI event-processing cadence (Sprint 5), per the spec's "every 5 minutes"
# target for the classification pipeline. Independent of the news-poll
# interval above -- this job drains whatever `raw_events`/`events` stubs
# have accumulated since the last pass, regardless of which adapter(s)
# produced them.
EVENT_PROCESSING_INTERVAL_MINUTES = 5

# Alert dispatch cadence (Sprint 6). Runs frequently -- BREAKING-tier
# opportunities have a p50 latency target of seconds (see README SLA
# targets), and this job is cheap (it's just checking for un-alerted
# opportunities, not doing any classification/scoring work itself), so a
# short interval doesn't strain the daily AI spend cap the way a tighter
# event-processing interval would.
ALERT_DISPATCH_INTERVAL_MINUTES = 1

# Daily briefing send time (UTC). Mid-day UTC covers both US premarket
# and APAC/EU market hours reasonably -- adjust per deployment if the
# target audience skews to one region.
DAILY_BRIEFING_HOUR_UTC = 13

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


async def run_news_ingestion_job() -> None:
    """Job wrapper: run one news/SEC/company-IR/X poll cycle. The worker
    manages its own DB sessions per adapter (see
    app.workers.news_ingestion.poll_adapter), so there's no session to
    open/close here -- just top-level error containment so one bad cycle
    doesn't kill the scheduled job."""
    try:
        persisted = await run_news_ingestion_poll()
        logger.info("Scheduled news ingestion poll complete: %d new raw events", persisted)
    except Exception:
        logger.exception("Unhandled error in scheduled news ingestion job")


async def run_event_processing_job() -> None:
    """Job wrapper: run one AI event-analysis pass (Sprint 5). The worker
    manages its own DB session (see
    app.workers.event_processing.run_event_processing_poll), so there's
    no session to open/close here -- just top-level error containment,
    matching run_news_ingestion_job."""
    try:
        summary = await run_event_processing_poll()
        logger.info(
            "Scheduled event processing complete: %d analyzed, %d reused, "
            "%d skipped, %d queued, %d failed",
            summary.analyzed, summary.reused_from_cluster,
            summary.skipped_insufficient_content, summary.queued_cap_exceeded,
            len(summary.failed),
        )
    except Exception:
        logger.exception("Unhandled error in scheduled event processing job")


async def run_alert_dispatch_job() -> None:
    """Job wrapper: run one Telegram alert-dispatch pass (Sprint 6). The
    worker manages its own DB session (see
    app.workers.alerts.run_alert_dispatch_poll), so there's no session to
    open/close here -- just top-level error containment, matching the
    other poll job wrappers above."""
    try:
        count = await run_alert_dispatch_poll()
        logger.info("Scheduled alert dispatch complete: %d opportunities evaluated", count)
    except Exception:
        logger.exception("Unhandled error in scheduled alert dispatch job")


async def run_daily_briefing_scheduled_job() -> None:
    """Job wrapper: generate + send the daily briefing (Sprint 6)."""
    try:
        await generate_daily_briefing()
        logger.info("Daily briefing sent")
    except Exception:
        logger.exception("Unhandled error generating/sending daily briefing")


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
        run_news_ingestion_job,
        trigger=IntervalTrigger(minutes=NEWS_INGESTION_INTERVAL_MINUTES),
        id="news_ingestion_poll",
        name="News/SEC/Company-IR/X ingestion poll",
        replace_existing=True,
        next_run_time=None,  # first run scheduled by the interval, not immediately
    )

    scheduler.add_job(
        run_event_processing_job,
        trigger=IntervalTrigger(minutes=EVENT_PROCESSING_INTERVAL_MINUTES),
        id="event_processing_poll",
        name="AI event classification/entity/impact analysis poll",
        replace_existing=True,
        next_run_time=None,  # first run scheduled by the interval, not immediately
    )

    scheduler.add_job(
        run_alert_dispatch_job,
        trigger=IntervalTrigger(minutes=ALERT_DISPATCH_INTERVAL_MINUTES),
        id="alert_dispatch_poll",
        name="Telegram alert dispatch poll",
        replace_existing=True,
        next_run_time=None,  # first run scheduled by the interval, not immediately
    )

    scheduler.add_job(
        run_daily_briefing_scheduled_job,
        trigger=CronTrigger(hour=DAILY_BRIEFING_HOUR_UTC, minute=0),
        id="daily_briefing",
        name="Daily Telegram briefing",
        replace_existing=True,
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
