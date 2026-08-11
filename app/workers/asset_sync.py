"""Asset synchronization job (Sprint 2).

Runs hourly. Fetches the live list of MEXC futures instruments and
reconciles it against our maintained `assets` table:

- If an asset's mexc_symbol is no longer live/enabled on MEXC, mark it
  inactive (active=False) rather than deleting it, so historical
  events/opportunities tied to it remain valid.
- If a previously-inactive asset's symbol comes back online, reactivate it.
- New symbols found on MEXC that aren't in our 52-asset seed are logged for
  manual review (auto-adding to the universe is out of scope for v1; the
  universe is intentionally curated).
- On MEXC failure, do NOT modify the DB. Log the failure explicitly and
  return a result indicating degraded/skipped sync, consistent with the
  project's "no silent failures" principle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.exceptions import MEXCAPIError
from app.market.mexc import MEXCClient

logger = logging.getLogger(__name__)


@dataclass
class AssetSyncResult:
    """Summary of what an asset-sync run did, for logging/alerting/tests."""

    ok: bool
    reactivated: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)
    unmatched_live_symbols: list[str] = field(default_factory=list)
    error: str | None = None
    ran_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def changed_count(self) -> int:
        return len(self.reactivated) + len(self.deactivated)


async def sync_assets(db: Session, client: MEXCClient | None = None) -> AssetSyncResult:
    """Reconcile the `assets` table against live MEXC instruments.

    Returns an AssetSyncResult describing what changed. Never raises for
    MEXC-side failures -- those are captured in the result (ok=False,
    error=...) so the scheduler/worker can log and move on rather than
    crashing the whole job loop.
    """
    client = client or MEXCClient()

    try:
        instruments = await client.fetch_instruments()
    except MEXCAPIError as exc:
        logger.error("Asset sync skipped: MEXC instrument fetch failed: %s", exc)
        return AssetSyncResult(ok=False, error=str(exc))

    live_active_symbols = {
        MEXCClient.normalize_symbol(inst.symbol) for inst in instruments if inst.is_active
    }
    live_all_symbols = {MEXCClient.normalize_symbol(inst.symbol) for inst in instruments}

    result = AssetSyncResult(ok=True)

    assets = db.query(Asset).all()
    tracked_symbols = set()
    for asset in assets:
        normalized = MEXCClient.normalize_symbol(asset.mexc_symbol)
        tracked_symbols.add(normalized)
        is_live = normalized in live_active_symbols

        if is_live and not asset.active:
            asset.active = True
            asset.updated_at = datetime.utcnow()
            result.reactivated.append(asset.ticker)
            logger.info("Asset %s reactivated (live on MEXC)", asset.ticker)
        elif not is_live and asset.active:
            asset.active = False
            asset.updated_at = datetime.utcnow()
            result.deactivated.append(asset.ticker)
            logger.warning(
                "Asset %s deactivated (no longer live/enabled on MEXC as %s)",
                asset.ticker,
                asset.mexc_symbol,
            )

    db.commit()

    # Symbols live on MEXC that resemble tracked tickers' underlying but
    # aren't in our curated universe -- flagged for manual review, not
    # auto-added (entity/asset universe changes are deliberately curated).
    result.unmatched_live_symbols = sorted(live_all_symbols - tracked_symbols)

    logger.info(
        "Asset sync complete: %d reactivated, %d deactivated, %d unmatched live symbols",
        len(result.reactivated),
        len(result.deactivated),
        len(result.unmatched_live_symbols),
    )
    return result
