"""News/SEC/Company-IR/X ingestion worker (Sprint 4, extended by Sprint 7).

Polls every configured `SourceAdapter` on an interval (see
`app.workers.scheduler`), normalizes results into `raw_events` rows, and
immediately kicks off deduplication (`app.processing.deduplicate`) to
create the corresponding (unclassified) `Event` stub -- AI classification
is filled in later by Sprint 5's processing step.

Mirrors the "no silent failures" pattern used elsewhere in the codebase
(app.workers.asset_sync, app.market.prices): one adapter failing doesn't
stop the others from running, and after MAX_RETRIES consecutive failures
for the same adapter within a polling cycle it's recorded in
`dead_letter_events` for manual triage instead of being silently dropped.
This is especially relevant for Sprint 7's X adapter, which is the most
failure-prone source (rate limits, API-tier changes) -- when it dead-
letters, Tier-1 companies' announcements still arrive via the
CompanyIRAdapter RSS feeds running alongside it, so coverage degrades
rather than disappears (see README risk mitigation #4).

Unlike market ingestion's persistent WebSocket task, source polling is
interval-based -- there's no long-lived connection to own, so this module
exposes a plain async function (`run_news_ingestion_poll`) for the
scheduler to call, plus a small worker object to hold adapter config and
the last-poll watermark between runs.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import DeadLetterEvent, RawEvent, Source, SourceAccount
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.processing.deduplicate import deduplicate_and_create_event

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
# How far back to look on a cold start / after an outage; subsequent runs
# use "since last successful poll" instead (see NewsIngestionWorker).
DEFAULT_LOOKBACK = timedelta(hours=1)

# Static credibility tiers by source_type, per the project's credibility
# cold-start plan (regulator/IR ~0.9, wire service ~0.8, analyst ~0.6,
# social ~0.3). Used only as a fallback when a Source row doesn't already
# exist -- scripts/seed_sources.py is the source of truth for the initial
# set and can be re-run to adjust tiers.
_DEFAULT_TIER_BY_SOURCE_TYPE = {
    "sec": (1, 0.9),
    "company_ir": (1, 0.9),
    "news": (2, 0.75),
    "x": (3, 0.5),
}

# X account_types considered Tier-1 for Sprint 7's initial rollout
# (company handles, CEOs/execs, regulators). Tier-2 (journalists,
# analysts) is deferred to a later pass once Tier-1 has run cleanly.
_X_TIER1_ACCOUNT_TYPES = ("company", "ceo", "regulator")


def get_or_create_source(db: Session, source_name: str, source_type: str) -> Source:
    source = db.query(Source).filter(Source.name == source_name).first()
    if source:
        return source

    tier, score = _DEFAULT_TIER_BY_SOURCE_TYPE.get(source_type, (3, 0.5))
    source = Source(
        name=source_name,
        source_type=source_type,
        credibility_tier=tier,
        credibility_score=score,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def get_or_create_source_account(
    db: Session, source: Source, external_account_id: str, account_name: str
) -> Optional[SourceAccount]:
    if not external_account_id:
        return None
    account = (
        db.query(SourceAccount)
        .filter(SourceAccount.source_id == source.id, SourceAccount.account_id == external_account_id)
        .first()
    )
    if account:
        return account
    account = SourceAccount(
        source_id=source.id,
        account_id=external_account_id,
        account_name=account_name,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def persist_normalized_event(db: Session, event: NormalizedEvent) -> Optional[RawEvent]:
    """Insert one `raw_events` row for `event`, deduplicating on
    (source_id, source_event_id) via the table's unique constraint.

    Returns the persisted RawEvent, or None if it was already ingested
    (duplicate) -- not an error, just idempotent re-polling (adapters'
    `since` windows can overlap by design to avoid gaps).
    """
    source = get_or_create_source(db, event.source_name, event.source_type)
    source_account = get_or_create_source_account(
        db, source, event.source_account_external_id or "", event.author or event.source_name
    )

    raw_event = RawEvent(
        id=f"RAW-{uuid.uuid4().hex[:28]}",
        source_id=source.id,
        source_account_id=source_account.id if source_account else None,
        source_event_id=event.source_event_id,
        author=event.author,
        published_at=event.published_at,
        title=event.title,
        content=event.content,
        url=event.url,
        language=event.language,
        raw_metadata=event.raw_metadata,
    )
    db.add(raw_event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None

    try:
        deduplicate_and_create_event(db, raw_event)
    except Exception:
        # Dedup/Event-stub creation failing shouldn't lose the raw event
        # (already committed and immutable) -- log and move on. Sprint 5's
        # processing worker can re-scan raw_events with no matching Event
        # row to pick this back up.
        db.rollback()
        logger.exception("Failed to create Event stub for raw_event %s", raw_event.id)

    return raw_event


def record_dead_letter(db: Session, adapter: SourceAdapter, error: Exception, attempts: int) -> None:
    db.add(
        DeadLetterEvent(
            source_name=adapter.source_name,
            source_type=adapter.source_type,
            error_message=str(error)[:2000],
            attempts=attempts,
            occurred_at=datetime.utcnow(),
        )
    )
    db.commit()
    logger.error(
        "Adapter %s dead-lettered after %d attempts: %s",
        adapter.source_name, attempts, error,
    )


async def poll_adapter(db: Session, adapter: SourceAdapter, since: Optional[datetime]) -> int:
    """Fetch + persist events for one adapter, retrying transient
    IngestionErrors up to MAX_RETRIES before dead-lettering. Returns the
    count of newly persisted raw events."""
    last_error: Optional[Exception] = None
    events: Sequence[NormalizedEvent] = []

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            events = await adapter.fetch_events(since=since)
            last_error = None
            break
        except IngestionError as exc:
            last_error = exc
            logger.warning(
                "Adapter %s fetch failed (attempt %d/%d): %s",
                adapter.source_name, attempt, MAX_RETRIES, exc,
            )

    if last_error is not None:
        record_dead_letter(db, adapter, last_error, MAX_RETRIES)
        return 0

    persisted = 0
    for event in events:
        try:
            if persist_normalized_event(db, event) is not None:
                persisted += 1
        except Exception:
            db.rollback()
            logger.exception(
                "Failed to persist event from %s (source_event_id=%s)",
                adapter.source_name, event.source_event_id,
            )

    logger.info("Adapter %s: %d new raw events persisted", adapter.source_name, persisted)
    return persisted


class NewsIngestionWorker:
    """Owns the configured adapter set and the last-successful-poll
    watermark used to compute `since` on each run."""

    def __init__(self, adapters: Sequence[SourceAdapter]):
        self._adapters = list(adapters)
        self._last_polled: Optional[datetime] = None

    async def poll_once(self) -> int:
        since = self._last_polled or (datetime.utcnow() - DEFAULT_LOOKBACK)
        db = SessionLocal()
        total_persisted = 0
        try:
            for adapter in self._adapters:
                total_persisted += await poll_adapter(db, adapter, since)
        finally:
            db.close()
        self._last_polled = datetime.utcnow()
        return total_persisted


_worker: Optional[NewsIngestionWorker] = None


def _build_x_adapter(db: Session) -> Optional[SourceAdapter]:
    """Build the Sprint 7 X adapter, or None if the feature flag is off,
    the bearer token is missing, or no Tier-1 accounts are seeded yet.
    Kept as its own function (rather than inlined into
    `_build_default_adapters`) so the gating logic is easy to unit test
    on its own."""
    from app.config.settings import get_settings
    from app.config.system_config import get_config_value
    from app.ingestion.x.adapter import XAdapter
    from app.ingestion.x.x_client import XClient

    if not get_config_value(db, "x_integration_enabled"):
        return None

    settings = get_settings()
    if not settings.x_api_key:
        logger.warning("x_integration_enabled but X_API_KEY (bearer token) is not configured; skipping XAdapter")
        return None

    tier1_accounts = (
        db.query(SourceAccount)
        .join(Source, SourceAccount.source_id == Source.id)
        .filter(Source.source_type == "x", SourceAccount.account_type.in_(_X_TIER1_ACCOUNT_TYPES))
        .all()
    )
    tier1_usernames = [acct.account_id for acct in tier1_accounts if acct.account_id]
    if not tier1_usernames:
        logger.warning("x_integration_enabled but no Tier-1 X accounts are seeded yet; skipping XAdapter")
        return None

    # settings.x_api_key doubles as the bearer token field -- X API v2's
    # app-only auth uses a single bearer token, and Settings doesn't need
    # a separate field for it (x_api_secret is reserved for a future
    # OAuth1 user-context upgrade, not needed for recent-search).
    return XAdapter(XClient(bearer_token=settings.x_api_key), tier1_usernames)


def _build_default_adapters() -> list[SourceAdapter]:
    """Build the default adapter set from settings + the tracked asset
    universe. Kept separate from `NewsIngestionWorker` so tests can inject
    a custom adapter list directly instead of going through settings/DB."""
    from app.config.settings import get_settings
    from app.db.models import Asset, Source, SourceAccount
    from app.ingestion.company_ir.adapter import CompanyIRAdapter, RSSFeedSource
    from app.ingestion.news.adapter import NewsAdapter
    from app.ingestion.news.newsapi_client import NewsAPIClient
    from app.ingestion.sec.adapter import SECAdapter
    from app.ingestion.sec.edgar_client import SECEDGARClient

    settings = get_settings()
    db = SessionLocal()
    try:
        company_names = [
            a.company_name for a in db.query(Asset).filter(Asset.active == True).all()  # noqa: E712
        ]
        ir_feeds = (
            db.query(SourceAccount)
            .join(Source, SourceAccount.source_id == Source.id)
            .filter(Source.source_type == "company_ir")
            .all()
        )
        x_adapter = _build_x_adapter(db)
    finally:
        db.close()

    adapters: list[SourceAdapter] = []

    if settings.news_api_key and company_names:
        adapters.append(NewsAdapter(NewsAPIClient(api_key=settings.news_api_key), company_names))
    else:
        logger.warning("NewsAdapter not configured: missing news_api_key or empty asset universe")

    if company_names:
        adapters.append(SECAdapter(SECEDGARClient(user_agent=settings.sec_user_agent), company_names))

    if ir_feeds:
        feed_sources = [
            RSSFeedSource(company_name=acct.account_name, feed_url=acct.url)
            for acct in ir_feeds
            if acct.url
        ]
        if feed_sources:
            adapters.append(CompanyIRAdapter(feed_sources))
    # No IR feeds configured yet is expected on a fresh install (see
    # scripts/seed_sources.py's COMPANY_IR_FEEDS) -- not logged as a
    # warning since it's not a misconfiguration, just an empty seed.

    if x_adapter is not None:
        adapters.append(x_adapter)

    return adapters


async def start_news_ingestion() -> None:
    """Initialize the process-wide news ingestion worker (idempotent).
    Actual polling is triggered by the scheduler job
    (`app.workers.scheduler.run_news_ingestion_job`), not a long-lived
    loop -- unlike market ingestion's persistent WebSocket, source polling
    is interval-based."""
    global _worker
    if _worker is None:
        _worker = NewsIngestionWorker(_build_default_adapters())


async def run_news_ingestion_poll() -> int:
    """Scheduler entry point: run one poll cycle across all adapters."""
    global _worker
    if _worker is None:
        await start_news_ingestion()
    return await _worker.poll_once()
