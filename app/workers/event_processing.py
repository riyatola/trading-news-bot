"""AI event-analysis worker (Sprint 5).

Scans `events` rows with `processed_at IS NULL` (created as unclassified
stubs by `app.processing.deduplicate` immediately after ingestion -- see
`app.workers.news_ingestion.persist_normalized_event`) and, for each:

1. Runs the pre-filter gate (`app.intelligence.prefilter`) -- skip if the
   raw event has too little content, or reuse a same-cluster sibling's
   classification if one already exists.
2. Otherwise checks the daily AI spend cap (`app.intelligence.cost_tracker`);
   if exceeded, leaves the event unprocessed (queued for the next poll,
   once the next UTC day's spend resets) rather than calling the LLM.
3. Calls the LLM (`app.intelligence.analyzer.analyze_event`) and persists
   the classification onto `events`, the extracted assets onto
   `event_entities`, and the impact summary onto `event_impacts`.

Mirrors the "no silent failures" pattern used elsewhere (see
`app.workers.news_ingestion`, `app.workers.asset_sync`): a single event's
LLM call failing doesn't stop the batch, is logged, and the event is left
with `processed_at IS NULL` so it's retried on the next poll --
`is_reprocessable` is preserved for a later Sprint 8 admin
reprocess-on-demand endpoint.

Interval-based like news ingestion (not a persistent connection), so this
module exposes a plain async poll function for the scheduler to call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.config.system_config import get_config_value
from app.db.database import SessionLocal
from app.db.models import Asset, Event, EventEntity, EventImpact, RawEvent
from app.exceptions import OpenAIError
from app.intelligence import cost_tracker
from app.intelligence.analyzer import AnalysisResult, analyze_event
from app.intelligence.openai_client import OpenAIClient
from app.intelligence.prefilter import PrefilterAction, decide as prefilter_decide

logger = logging.getLogger(__name__)


@dataclass
class ProcessingSummary:
    """Summary of one poll cycle, for logging/alerting/tests."""

    analyzed: int = 0
    reused_from_cluster: int = 0
    skipped_insufficient_content: int = 0
    queued_cap_exceeded: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def total_handled(self) -> int:
        return self.analyzed + self.reused_from_cluster + self.skipped_insufficient_content


def get_pending_events(db: Session, limit: int) -> list[Event]:
    """Unclassified events, oldest first (FIFO -- keeps latency bounded
    for any one story instead of always picking the newest)."""
    return (
        db.query(Event)
        .filter(Event.processed_at.is_(None))
        .order_by(Event.created_at.asc())
        .limit(limit)
        .all()
    )


def get_tracked_assets(db: Session) -> list[Asset]:
    return db.query(Asset).filter(Asset.active == True).all()  # noqa: E712


def apply_skip(db: Session, event: Event, reason: str) -> None:
    """Mark a low-content event as handled without classifying it, so it
    doesn't get re-picked-up every poll cycle. Left reprocessable in case
    the raw event's content is later enriched (not currently done, but
    cheap to allow)."""
    event.processed_at = datetime.utcnow()
    event.reasoning_summary = reason
    event.is_reprocessable = True
    db.commit()


def apply_cluster_reuse(db: Session, event: Event, source: Event) -> None:
    """Copy a same-cluster sibling's classification (+ entities + impact)
    onto `event` instead of spending another LLM call on the same story."""
    event.event_type = source.event_type
    event.direction = source.direction
    event.severity = source.severity
    event.confidence = source.confidence
    event.time_horizon = source.time_horizon
    event.novelty = source.novelty
    event.macro_relevance = source.macro_relevance
    event.catalyst = source.catalyst
    event.reasoning_summary = f"[Reused from cluster sibling {source.id}] {source.reasoning_summary or ''}".strip()
    event.processed_at = datetime.utcnow()
    event.is_reprocessable = True

    for entity in db.query(EventEntity).filter(EventEntity.event_id == source.id).all():
        db.add(
            EventEntity(
                event_id=event.id,
                asset_id=entity.asset_id,
                relationship=entity.relationship,
                direction=entity.direction,
                impact=entity.impact,
                confidence=entity.confidence,
            )
        )

    source_impact = db.query(EventImpact).filter(EventImpact.event_id == source.id).first()
    if source_impact is not None:
        db.add(
            EventImpact(
                event_id=event.id,
                summary=source_impact.summary,
                macro_relevance=source_impact.macro_relevance,
                cross_asset_effects=source_impact.cross_asset_effects,
            )
        )

    db.commit()


def apply_analysis(db: Session, event: Event, result: AnalysisResult, assets_by_ticker: dict[str, Asset]) -> None:
    """Persist a fresh LLM analysis onto `event` + its entities/impact."""
    analysis = result.analysis

    event.event_type = analysis.event_type
    event.direction = analysis.direction
    event.severity = analysis.severity
    event.confidence = analysis.confidence
    event.time_horizon = analysis.time_horizon
    event.novelty = analysis.novelty
    event.macro_relevance = analysis.macro_relevance
    event.catalyst = analysis.catalyst
    event.reasoning_summary = analysis.reasoning_summary
    event.processed_at = datetime.utcnow()
    event.is_reprocessable = True

    for entity in analysis.entities:
        asset = assets_by_ticker.get(entity.ticker)
        if asset is None:
            continue  # already filtered in analyze_event, defensive here too
        db.add(
            EventEntity(
                event_id=event.id,
                asset_id=asset.id,
                relationship=entity.relationship,
                direction=entity.direction,
                impact=entity.impact,
                confidence=entity.confidence,
            )
        )

    db.add(
        EventImpact(
            event_id=event.id,
            summary=analysis.impact_summary,
            macro_relevance={
                "score": analysis.macro_relevance,
                "detail": analysis.macro_relevance_detail,
            },
            cross_asset_effects=[
                {
                    "ticker": e.ticker,
                    "relationship": e.relationship,
                    "direction": e.direction,
                    "impact": e.impact,
                    "confidence": e.confidence,
                }
                for e in analysis.entities
            ],
        )
    )

    db.commit()
    cost_tracker.record_spend(
        db,
        event_id=event.id,
        model=get_settings().openai_model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )


async def process_pending_events(
    db: Session, client: OpenAIClient, batch_size: int | None = None
) -> ProcessingSummary:
    """Run one processing pass over pending events. Never raises for a
    single event's failure -- logged and left for retry next cycle."""
    settings = get_settings()
    batch_size = batch_size or int(get_config_value(db, "event_processing_batch_size"))

    summary = ProcessingSummary()
    tracked_assets = get_tracked_assets(db)
    assets_by_ticker = {a.ticker: a for a in tracked_assets}

    events = get_pending_events(db, batch_size)
    for event in events:
        raw_event = db.query(RawEvent).filter(RawEvent.id == event.raw_event_id).first()
        if raw_event is None:
            logger.error("Event %s has no matching raw_event %s; skipping", event.id, event.raw_event_id)
            summary.failed.append(event.id)
            continue

        decision = prefilter_decide(db, event, raw_event)

        if decision.action == PrefilterAction.SKIP_INSUFFICIENT_CONTENT:
            apply_skip(db, event, decision.reason)
            summary.skipped_insufficient_content += 1
            continue

        if decision.action == PrefilterAction.REUSE_CLUSTER:
            apply_cluster_reuse(db, event, decision.reuse_source)
            summary.reused_from_cluster += 1
            continue

        # ANALYZE: gated by the daily spend cap.
        if cost_tracker.is_daily_cap_exceeded(db):
            logger.warning(
                "Daily AI spend cap reached; queuing %d+ remaining pending events for next poll",
                len(events) - summary.total_handled,
            )
            summary.queued_cap_exceeded += 1
            break  # cap won't un-exceed itself mid-batch; stop rather than spin

        try:
            result = await analyze_event(client, raw_event, tracked_assets)
            apply_analysis(db, event, result, assets_by_ticker)
            summary.analyzed += 1
        except OpenAIError:
            db.rollback()
            logger.exception("Failed to analyze event %s", event.id)
            summary.failed.append(event.id)
        except Exception:
            db.rollback()
            logger.exception("Unexpected error analyzing event %s", event.id)
            summary.failed.append(event.id)

    logger.info(
        "Event processing pass complete: %d analyzed, %d reused, %d skipped (content), "
        "%d queued (cap), %d failed",
        summary.analyzed, summary.reused_from_cluster, summary.skipped_insufficient_content,
        summary.queued_cap_exceeded, len(summary.failed),
    )
    return summary


def _build_default_client() -> OpenAIClient:
    settings = get_settings()
    return OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
        timeout=settings.openai_timeout_seconds,
    )


async def run_event_processing_poll() -> ProcessingSummary:
    """Scheduler entry point: run one event-processing pass."""
    db = SessionLocal()
    try:
        client = _build_default_client()
        return await process_pending_events(db, client)
    finally:
        db.close()
