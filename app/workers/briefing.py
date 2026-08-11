"""Daily briefing generation (Sprint 6).

Runs once per day (see `app.workers.scheduler`'s cron trigger) and posts a
single DAILY-channel summary: macro regime, the day's highest-scoring
opportunities, current watchlist-tier tickers, and a pointer to open
risks. Pulls from data already computed by other sprints (macro
snapshots, opportunities) rather than doing its own analysis -- this
module is purely "summarize what already happened," same spirit as
`app.workers.asset_sync`'s reconciliation-not-computation role.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.database import SessionLocal
from app.db.models import Asset, Event, MacroSnapshot, Opportunity
from app.exceptions import TelegramError
from app.notifications import templates
from app.notifications.telegram import TelegramClient
from app.scoring.alert_decision import AlertChannel
from app.workers.alerts import get_channel_chat_id

logger = logging.getLogger(__name__)

LOOKBACK = timedelta(hours=24)
TOP_OPPORTUNITIES_LIMIT = 8
# Same tier boundary as AlertTier.WATCHLIST's default -- kept as a
# literal here rather than re-reading system_config, since the briefing
# is a summary of *all* activity in the window, not a live alert
# decision; operators can still see everything via GET /opportunities.
WATCHLIST_MIN_SCORE = 50


def get_latest_macro_snapshot(db: Session) -> MacroSnapshot | None:
    return db.query(MacroSnapshot).order_by(MacroSnapshot.timestamp.desc()).first()


def get_top_opportunities(db: Session, since: datetime, limit: int = TOP_OPPORTUNITIES_LIMIT) -> list[Opportunity]:
    opportunities = (
        db.query(Opportunity)
        .filter(Opportunity.created_at >= since, Opportunity.status == "active")
        .all()
    )
    opportunities.sort(
        key=lambda o: max(o.long_score or 0, o.short_score or 0, o.macro_score or 0),
        reverse=True,
    )
    return opportunities[:limit]


def get_watchlist_tickers(db: Session, since: datetime) -> list[str]:
    opportunities = (
        db.query(Opportunity)
        .filter(Opportunity.created_at >= since, Opportunity.status == "active")
        .all()
    )
    asset_ids = {
        o.asset_id
        for o in opportunities
        if max(o.long_score or 0, o.short_score or 0) >= WATCHLIST_MIN_SCORE
    }
    if not asset_ids:
        return []
    return sorted(a.ticker for a in db.query(Asset).filter(Asset.id.in_(asset_ids)).all())


def _enrich_opportunities(db: Session, opportunities: list[Opportunity]) -> list[dict]:
    """Resolve (ticker, catalyst) for each opportunity so
    `app.notifications.templates.render_daily_briefing` stays a pure
    function with no DB access of its own."""
    enriched = []
    for o in opportunities:
        event = db.query(Event).filter(Event.id == o.event_id).first()
        asset = db.query(Asset).filter(Asset.id == o.asset_id).first()
        if event is None or asset is None:
            continue
        enriched.append(
            {
                "ticker": asset.ticker,
                "opportunity_type": o.opportunity_type,
                "score": max(o.long_score or 0, o.short_score or 0, o.macro_score or 0),
                "catalyst": event.catalyst,
            }
        )
    return enriched


async def generate_and_send_briefing(db: Session, client: TelegramClient, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    since = now - LOOKBACK

    macro = get_latest_macro_snapshot(db)
    top_opportunities = _enrich_opportunities(db, get_top_opportunities(db, since))
    watchlist = get_watchlist_tickers(db, since)

    body = templates.render_daily_briefing(now, macro, top_opportunities, watchlist)

    chat_id, thread_id = get_channel_chat_id(db, AlertChannel.DAILY)
    try:
        await client.send_message(chat_id=chat_id, text=body, message_thread_id=thread_id)
    except TelegramError:
        logger.exception("Failed to deliver daily briefing")
        raise


async def run_daily_briefing_job() -> None:
    """Scheduler entry point: generate + send today's briefing. Errors
    propagate to the caller (see `app.workers.scheduler.run_daily_briefing_job`),
    which logs and moves on -- a missed briefing isn't retried mid-day,
    it's just resent tomorrow, consistent with a summary job (not a
    time-sensitive alert)."""
    db = SessionLocal()
    try:
        settings = get_settings()
        client = TelegramClient(bot_token=settings.telegram_bot_token)
        await generate_and_send_briefing(db, client)
    finally:
        db.close()
