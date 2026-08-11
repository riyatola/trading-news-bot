"""Market data endpoints (Sprint 3)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Asset, MarketSnapshot
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["market"])


def _serialize_snapshot(s: MarketSnapshot) -> dict:
    return {
        "timestamp": s.timestamp,
        "price": s.price,
        "mark_price": s.mark_price,
        "index_price": s.index_price,
        "volume_24h": s.volume_24h,
        "volume_1h": s.volume_1h,
        "open_interest": s.open_interest,
        "funding_rate": s.funding_rate,
        "basis": s.basis,
        "indicators": s.indicators,
    }


def _get_asset_or_404(db: Session, ticker: str) -> Asset:
    asset = db.query(Asset).filter(Asset.ticker == ticker.upper()).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {ticker.upper()} not found")
    return asset


@router.get("/{ticker}")
async def get_market_data(
    ticker: str,
    history_limit: int = Query(
        default=0, ge=0, le=500,
        description="Number of prior snapshots to include, most recent first",
    ),
    db: Session = Depends(get_db),
):
    """
    Get the latest market snapshot (price, volume, OI, funding, indicators)
    for an asset, plus optional recent history.

    Parameters:
        ticker: Asset ticker symbol (case-insensitive)
        history_limit: Number of prior snapshots to include (0 = latest only)

    Returns:
        dict: Asset identity, latest snapshot, and (optionally) recent
            history. `market_confirmation_available` is False when there's
            no market data yet for this asset (e.g. ingestion hasn't run,
            or MEXC has been unavailable) -- callers (notably the
            opportunity engine, Sprint 8) should treat this as degraded/
            unconfirmed rather than an error.
    """
    asset = _get_asset_or_404(db, ticker)

    latest = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.asset_id == asset.id)
        .order_by(MarketSnapshot.timestamp.desc())
        .first()
    )

    result = {
        "asset": {
            "id": asset.id,
            "ticker": asset.ticker,
            "company_name": asset.company_name,
        },
        "market_confirmation_available": latest is not None,
        "latest": _serialize_snapshot(latest) if latest else None,
        "history": [],
    }

    if history_limit:
        history = (
            db.query(MarketSnapshot)
            .filter(MarketSnapshot.asset_id == asset.id)
            .order_by(MarketSnapshot.timestamp.desc())
            .limit(history_limit)
            .all()
        )
        result["history"] = [_serialize_snapshot(s) for s in history]

    return result
