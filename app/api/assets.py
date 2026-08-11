"""Asset management endpoints (Sprint 2)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Asset, AssetRelationship
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assets", tags=["assets"])


def _serialize_asset(a: Asset) -> dict:
    return {
        "id": a.id,
        "ticker": a.ticker,
        "company_name": a.company_name,
        "mexc_symbol": a.mexc_symbol,
        "exchange_ticker": a.exchange_ticker,
        "sector": a.sector,
        "industry": a.industry,
        "country": a.country,
        "currency": a.currency,
        "active": a.active,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


def _get_asset_or_404(db: Session, ticker: str) -> Asset:
    asset = db.query(Asset).filter(Asset.ticker == ticker.upper()).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {ticker.upper()} not found")
    return asset


@router.get("")
async def get_assets(
    active_only: bool = True,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Get list of assets (the maintained 52 MEXC stock-perpetual universe).

    Parameters:
        active_only: Filter to active assets only (default True)
        sector: Filter by sector
        industry: Filter by industry
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        dict: total count + paginated list of assets with metadata
    """
    query = db.query(Asset)

    if active_only:
        query = query.filter(Asset.active == True)  # noqa: E712

    if sector:
        query = query.filter(Asset.sector == sector)

    if industry:
        query = query.filter(Asset.industry == industry)

    total = query.count()
    assets = query.order_by(Asset.ticker).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": [_serialize_asset(a) for a in assets],
    }


@router.get("/{ticker}")
async def get_asset(ticker: str, db: Session = Depends(get_db)):
    """
    Get asset by ticker.

    Parameters:
        ticker: Asset ticker symbol (case-insensitive)

    Returns:
        dict: Asset details
    """
    asset = _get_asset_or_404(db, ticker)
    return _serialize_asset(asset)


@router.get("/{ticker}/relationships")
async def get_asset_relationships(
    ticker: str,
    relationship_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Get relationships for an asset (competitors, suppliers, customers, sector/macro links).

    Parameters:
        ticker: Asset ticker symbol
        relationship_type: Filter by relationship type (e.g. "competitor", "supplier",
            "customer", "sector_peer", "macro_link")

    Returns:
        dict: Asset and related assets
    """
    asset = _get_asset_or_404(db, ticker)

    query = db.query(AssetRelationship).filter(AssetRelationship.source_asset_id == asset.id)

    if relationship_type:
        query = query.filter(AssetRelationship.relationship_type == relationship_type)

    relationships = query.all()

    result = {
        "asset": {
            "id": asset.id,
            "ticker": asset.ticker,
            "company_name": asset.company_name,
        },
        "relationships": [],
    }

    # Batch-load targets to avoid N+1 queries.
    target_ids = [rel.target_asset_id for rel in relationships]
    targets_by_id = {}
    if target_ids:
        for target in db.query(Asset).filter(Asset.id.in_(target_ids)).all():
            targets_by_id[target.id] = target

    for rel in relationships:
        target = targets_by_id.get(rel.target_asset_id)
        if target:
            result["relationships"].append({
                "target_ticker": target.ticker,
                "target_company": target.company_name,
                "relationship_type": rel.relationship_type,
                "strength": rel.strength,
                "direction": rel.direction,
                "confidence": rel.confidence,
                "source": rel.source,
            })

    return result
