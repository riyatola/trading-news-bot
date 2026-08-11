"""Telegram alert dispatch worker (Sprint 6).

Scans `opportunities` rows that don't yet have a *sent* `alerts` row
(fresh opportunities, or ones whose prior delivery attempt failed and is
still retryable) and, for each:

1. Runs the alert decision logic (`app.scoring.alert_decision.decide`)
   against the configurable 50/65/80/90 score thresholds.
2. Below the watchlist threshold: nothing is sent. Not treated as a
   terminal state -- Sprint 8's 15-minute opportunity-recalculation job
   can raise the score on a later pass and this worker will pick it up
   then, since no `Alert` row was ever created.
3. At/above threshold: renders the channel-appropriate template
   (`app.notifications.templates`) and sends via
   `app.notifications.telegram.TelegramClient`.
4. CRITICAL-tier LONG/SHORT/MACRO opportunities are *also* mirrored to
   BREAKING (two `Alert` rows, one per channel) -- that channel exists
   specifically to surface the most urgent items regardless of type.

Mirrors the "no silent failures" pattern used elsewhere
(`app.workers.event_processing`, `app.workers.news_ingestion`): one
alert's delivery failing is logged onto its `Alert` row
(`status="retrying"`, `last_error`, `delivery_attempts` incremented) and
retried on the next poll up to MAX_DELIVERY_ATTEMPTS, rather than
stopping the batch or losing the opportunity.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.config.system_config import get_config_value
from app.db.database import SessionLocal
from app.db.models import (
    Alert, Asset, Event, EventEntity, MarketSnapshot, Opportunity, RawEvent,
)
from app.exceptions import TelegramError
from app.notifications import templates
from app.notifications.telegram import TelegramClient
from app.scoring.alert_decision import AlertChannel, AlertTier, decide

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 3
# How many opportunities to evaluate per poll -- mirrors the role of
# event_processing_batch_size in Sprint 5, keeping one slow cycle from
# starving the scheduler's other jobs.
DEFAULT_BATCH_SIZE = 25


def get_channel_chat_id(db: Session, channel: AlertChannel) -> tuple[str, Optional[int]]:
    """Resolve (chat_id, message_thread_id) for a channel.

    `telegram_channel_map` in system_config lets each channel point at a
    distinct chat_id (separate bot chats/channels) OR a shared supergroup
    with per-channel topic threads (message_thread_id) -- whichever the
    operator has actually set up:

        {"LONG": {"chat_id": "-100123", "message_thread_id": 4}, ...}

    Falls back to a single chat with no topic (Settings.telegram_chat_id)
    for a fresh install that hasn't configured per-channel routing yet.
    """
    settings = get_settings()
    channel_map = get_config_value(db, "telegram_channel_map") or {}
    entry = channel_map.get(channel.value)
    if entry:
        return str(entry.get("chat_id", settings.telegram_chat_id)), entry.get("message_thread_id")
    return settings.telegram_chat_id, None


def get_pending_opportunities(db: Session, limit: int) -> list[Opportunity]:
    """Active opportunities with no alert yet, or only a still-retryable
    failed alert, oldest first (FIFO, same rationale as
    `app.workers.event_processing.get_pending_events`)."""
    sent_or_new_ids = {
        row[0] for row in db.query(Alert.opportunity_id).filter(Alert.status == "sent").all()
    }
    fresh = (
        db.query(Opportunity)
        .filter(Opportunity.status == "active")
        .order_by(Opportunity.created_at.asc())
        .all()
    )
    fresh = [o for o in fresh if o.id not in sent_or_new_ids]

    retrying_ids = {
        row[0]
        for row in (
            db.query(Alert.opportunity_id)
            .filter(Alert.status == "retrying", Alert.delivery_attempts < MAX_DELIVERY_ATTEMPTS)
            .all()
        )
    }
    retrying_ids -= {o.id for o in fresh}
    if retrying_ids:
        fresh += (
            db.query(Opportunity)
            .filter(Opportunity.id.in_(retrying_ids), Opportunity.status == "active")
            .all()
        )

    return fresh[:limit]


def _load_context(db: Session, opportunity: Opportunity) -> Optional[dict]:
    """Pull the Event/RawEvent/Asset/entities/latest-market-snapshot an
    alert template needs. Returns None (logged) if required rows are
    missing -- a data-integrity issue, not a retryable delivery failure,
    so the caller skips rather than loops forever."""
    event = db.query(Event).filter(Event.id == opportunity.event_id).first()
    if event is None:
        logger.error("Opportunity %s references missing event %s", opportunity.id, opportunity.event_id)
        return None

    raw_event = db.query(RawEvent).filter(RawEvent.id == event.raw_event_id).first()
    asset = db.query(Asset).filter(Asset.id == opportunity.asset_id).first()
    if raw_event is None or asset is None:
        logger.error("Opportunity %s missing raw_event/asset context", opportunity.id)
        return None

    entities = db.query(EventEntity).filter(EventEntity.event_id == event.id).all()
    related_ids = {e.asset_id for e in entities} | {asset.id}
    assets_by_id = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(related_ids)).all()}

    market_snapshot = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.asset_id == asset.id)
        .order_by(MarketSnapshot.timestamp.desc())
        .first()
    )

    return {
        "event": event,
        "raw_event": raw_event,
        "asset": asset,
        "entities": entities,
        "assets_by_id": assets_by_id,
        "market_snapshot": market_snapshot,
    }


def render_for_channel(channel: AlertChannel, opportunity: Opportunity, ctx: dict) -> tuple[str, str]:
    """Returns (title, body) for the given channel."""
    if channel == AlertChannel.LONG:
        title = f"LONG: {ctx['asset'].ticker}"
        body = templates.render_long_alert(
            opportunity, ctx["event"], ctx["raw_event"], ctx["asset"],
            ctx["entities"], ctx["assets_by_id"], ctx["market_snapshot"],
        )
    elif channel == AlertChannel.SHORT:
        title = f"SHORT: {ctx['asset'].ticker}"
        body = templates.render_short_alert(
            opportunity, ctx["event"], ctx["raw_event"], ctx["asset"],
            ctx["entities"], ctx["assets_by_id"], ctx["market_snapshot"],
        )
    elif channel == AlertChannel.MACRO:
        title = f"MACRO: {ctx['event'].catalyst}"
        body = templates.render_macro_alert(
            opportunity, ctx["event"], ctx["raw_event"], ctx["entities"], ctx["assets_by_id"],
        )
    elif channel == AlertChannel.MARKET:
        title = f"MARKET: {ctx['asset'].ticker}"
        body = templates.render_market_alert(opportunity, ctx["asset"], ctx["market_snapshot"], ctx["event"])
    elif channel == AlertChannel.BREAKING:
        title = f"BREAKING: {ctx['asset'].ticker}"
        if (opportunity.long_score or 0) >= (opportunity.short_score or 0):
            inner = templates.render_long_alert(
                opportunity, ctx["event"], ctx["raw_event"], ctx["asset"],
                ctx["entities"], ctx["assets_by_id"], ctx["market_snapshot"],
            )
        else:
            inner = templates.render_short_alert(
                opportunity, ctx["event"], ctx["raw_event"], ctx["asset"],
                ctx["entities"], ctx["assets_by_id"], ctx["market_snapshot"],
            )
        body = templates.render_breaking_wrapper(inner)
    else:  # RESEARCH
        title = f"RESEARCH: {ctx['asset'].ticker}"
        body = templates.render_research_alert(opportunity, ctx["event"], ctx["raw_event"])
    return title, body


async def _send_channel_alert(
    db: Session, client: TelegramClient, opportunity: Opportunity, channel: AlertChannel, ctx: dict
) -> None:
    existing = (
        db.query(Alert)
        .filter(Alert.opportunity_id == opportunity.id, Alert.alert_type == channel.value)
        .first()
    )
    if existing is not None and existing.status == "sent":
        return

    title, body = render_for_channel(channel, opportunity, ctx)

    alert = existing or Alert(
        id=f"ALT-{uuid.uuid4().hex[:20]}",
        opportunity_id=opportunity.id,
        alert_type=channel.value,
        title=title,
        body=body,
    )
    alert.title = title
    alert.body = body

    chat_id, thread_id = get_channel_chat_id(db, channel)
    try:
        result = await client.send_message(chat_id=chat_id, text=body, message_thread_id=thread_id)
        alert.telegram_message_id = result.message_id
        alert.telegram_channel = channel.value
        alert.status = "sent"
        alert.sent_at = datetime.utcnow()
    except TelegramError as exc:
        alert.delivery_attempts = (alert.delivery_attempts or 0) + 1
        alert.last_error = str(exc)[:2000]
        alert.status = "failed" if alert.delivery_attempts >= MAX_DELIVERY_ATTEMPTS else "retrying"
        logger.warning(
            "Alert delivery failed for opportunity %s channel %s (attempt %d/%d): %s",
            opportunity.id, channel.value, alert.delivery_attempts, MAX_DELIVERY_ATTEMPTS, exc,
        )

    if existing is None:
        db.add(alert)
    db.commit()


async def dispatch_one(db: Session, client: TelegramClient, opportunity: Opportunity) -> None:
    decision = decide(db, opportunity)
    if not decision.should_send or decision.channel is None:
        return

    ctx = _load_context(db, opportunity)
    if ctx is None:
        return

    channels = [decision.channel]
    if decision.tier == AlertTier.CRITICAL and decision.channel in (
        AlertChannel.LONG, AlertChannel.SHORT, AlertChannel.MACRO,
    ):
        channels.append(AlertChannel.BREAKING)

    for channel in channels:
        await _send_channel_alert(db, client, opportunity, channel, ctx)


async def dispatch_pending_alerts(db: Session, client: TelegramClient, batch_size: int | None = None) -> int:
    """Run one dispatch pass. Never raises for a single opportunity's
    failure -- logged and left for retry next cycle."""
    batch_size = batch_size or DEFAULT_BATCH_SIZE
    opportunities = get_pending_opportunities(db, batch_size)

    for opportunity in opportunities:
        try:
            await dispatch_one(db, client, opportunity)
        except Exception:
            db.rollback()
            logger.exception("Unhandled error dispatching alert for opportunity %s", opportunity.id)

    return len(opportunities)


def _build_default_client() -> TelegramClient:
    settings = get_settings()
    return TelegramClient(bot_token=settings.telegram_bot_token)


async def run_alert_dispatch_poll() -> int:
    """Scheduler entry point: run one alert-dispatch pass."""
    db = SessionLocal()
    try:
        client = _build_default_client()
        return await dispatch_pending_alerts(db, client)
    finally:
        db.close()
