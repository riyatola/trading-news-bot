"""Market data ingestion worker (Sprint 3).

Bridges the MEXC WebSocket stream (`app.market.prices`) to the
`market_snapshots` table: for each tick, resolves the MEXC symbol to a
tracked Asset, computes indicators from that asset's recent snapshot
history (`app.market.indicators`), and persists a `MarketSnapshot` row.

Runs as a long-lived asyncio task started at app startup (see
`app.main.startup_event`), not an APScheduler interval job -- it holds a
persistent WebSocket connection rather than firing periodically. Business
logic (`load_symbol_map`, `load_history`, `should_persist`, `persist_tick`)
takes an injected `Session` so it can be unit tested directly, mirroring
the pattern used in `app.workers.asset_sync.sync_assets`; only the
process-level job wrapper (`_persist_tick_job`) opens its own
`SessionLocal`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Asset, MarketSnapshot
from app.market.indicators import RETURN_HORIZONS, PricePoint, compute_indicators
from app.market.prices import MEXCWebSocketClient, MarketTick

logger = logging.getLogger(__name__)

# Don't persist more than one snapshot per asset within this window --
# MEXC can push ticker updates multiple times a second, and we don't need
# (or want to pay the storage cost for) sub-second granularity.
MIN_SNAPSHOT_INTERVAL = timedelta(seconds=5)

# How far back to pull history when computing indicators. Must cover the
# longest return horizon we track (30d) with headroom.
HISTORY_LOOKBACK = max(RETURN_HORIZONS.values()) + timedelta(days=1)


def load_symbol_map(db: Session) -> dict[str, str]:
    """mexc_symbol (normalized) -> asset_id, for active tracked assets."""
    assets = db.query(Asset).filter(Asset.active == True).all()  # noqa: E712
    return {a.mexc_symbol.replace("_", "").replace("-", "").upper(): a.id for a in assets}


def load_history(db: Session, asset_id: str, before: datetime) -> list[PricePoint]:
    """Prior snapshots for `asset_id` in [before - HISTORY_LOOKBACK, before)."""
    cutoff = before - HISTORY_LOOKBACK
    rows = (
        db.query(MarketSnapshot)
        .filter(
            MarketSnapshot.asset_id == asset_id,
            MarketSnapshot.timestamp >= cutoff,
            MarketSnapshot.timestamp < before,
        )
        .order_by(MarketSnapshot.timestamp.asc())
        .all()
    )
    return [PricePoint(timestamp=r.timestamp, price=r.price, volume_1h=r.volume_1h) for r in rows]


def should_persist(asset_id: str, tick_timestamp: datetime, last_persisted: dict[str, datetime]) -> bool:
    """Throttle: skip if a snapshot was already persisted for this asset
    within MIN_SNAPSHOT_INTERVAL of `tick_timestamp`."""
    last = last_persisted.get(asset_id)
    return last is None or tick_timestamp - last >= MIN_SNAPSHOT_INTERVAL


def persist_tick(db: Session, asset_id: str, tick: MarketTick) -> Optional[MarketSnapshot]:
    """Compute indicators and insert one MarketSnapshot row for `asset_id`.

    Returns the persisted snapshot, or None if it was a duplicate
    (asset_id, timestamp) already committed by a concurrent write -- not
    treated as an error, just a race with the in-memory throttle.
    """
    history = load_history(db, asset_id, tick.timestamp)
    indicators = compute_indicators(
        current_price=tick.price,
        current_time=tick.timestamp,
        # MEXC's ticker push only carries 24h volume; hourly volume (and
        # therefore true relative-volume) is Sprint 3 backlog pending a
        # secondary MEXC channel.
        current_volume_1h=None,
        history=history,
    )

    snapshot = MarketSnapshot(
        asset_id=asset_id,
        timestamp=tick.timestamp,
        price=tick.price,
        mark_price=tick.mark_price,
        index_price=tick.index_price,
        volume_24h=tick.volume_24h,
        open_interest=tick.open_interest,
        funding_rate=tick.funding_rate,
        indicators=indicators,
    )
    db.add(snapshot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return snapshot


def _persist_tick_job(asset_id: str, tick: MarketTick) -> None:
    """Job wrapper: open + always close its own session (mirrors
    `app.workers.scheduler.run_asset_sync_job`)."""
    db = SessionLocal()
    try:
        persist_tick(db, asset_id, tick)
    except Exception:
        db.rollback()
        logger.exception("Failed to persist market snapshot for asset %s", asset_id)
    finally:
        db.close()


class MarketIngestionWorker:
    """Owns the WebSocket client + background asyncio task lifecycle, and
    the in-memory per-asset throttle state for the life of the process."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[MEXCWebSocketClient] = None
        self._last_persisted: dict[str, datetime] = {}

    async def _handle_tick(self, tick: MarketTick, symbol_map: dict[str, str]) -> None:
        asset_id = symbol_map.get(tick.symbol)
        if asset_id is None:
            return  # not one of our tracked assets (or a stale symbol map)
        if not should_persist(asset_id, tick.timestamp, self._last_persisted):
            return
        await asyncio.to_thread(_persist_tick_job, asset_id, tick)
        self._last_persisted[asset_id] = tick.timestamp

    async def start(self) -> None:
        if self._task is not None:
            return

        db = SessionLocal()
        try:
            symbol_map = load_symbol_map(db)
        finally:
            db.close()

        if not symbol_map:
            logger.warning("Market ingestion not started: no active assets to track")
            return

        self._client = MEXCWebSocketClient(symbols=list(symbol_map.keys()))
        self._task = asyncio.create_task(
            self._client.run(lambda tick: self._handle_tick(tick, symbol_map)),
            name="mexc_market_ingestion",
        )
        logger.info("Market ingestion worker started (%d symbols)", len(symbol_map))

    async def stop(self) -> None:
        if self._client is not None:
            self._client.stop()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Market ingestion worker stopped")


_worker: Optional[MarketIngestionWorker] = None


async def start_market_ingestion() -> None:
    """Start the process-wide market ingestion worker (idempotent)."""
    global _worker
    if _worker is None:
        _worker = MarketIngestionWorker()
    await _worker.start()


async def stop_market_ingestion() -> None:
    """Stop the process-wide market ingestion worker, if running."""
    global _worker
    if _worker is not None:
        await _worker.stop()
