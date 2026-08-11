"""Seed the `asset_relationships` table with a manually-curated entity graph.

Per the project's risk-mitigation strategy, the relationship graph is
hand-seeded from 10-K competitive/risk sections and well-known supply
chains, reviewed quarterly (see app.workers.scheduler). Auto-discovery of
new edges via LLM is explicitly deferred to v2.

Relationship types used:
- "competitor": direct product/market competitors (10-K "Competition" section)
- "supplier": source_asset supplies target_asset (source -> target dependency)
- "customer": inverse of supplier, kept explicit for readability of the
  graph in either traversal direction
- "sector_peer": same sector/industry, weaker correlation link than
  "competitor" (used for contagion-style sympathy moves)
- "macro_link": sensitivity to a specific macro variable (e.g. oil, rates)

Usage:
    python -m scripts.seed_relationships
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.db.database import SessionLocal, engine
from app.db.models import Asset, AssetRelationship, Base

logger = logging.getLogger(__name__)

# (source_ticker, target_ticker, relationship_type, strength, direction, confidence, source_note)
# strength/confidence are 0-1 scale, direction is qualitative sign of the
# expected co-movement/impact.
SEED_RELATIONSHIPS: list[tuple[str, str, str, float, str, float, str]] = [
    # --- Semiconductor competitors (10-K "Competition" sections) ---
    ("NVDA", "AMD", "competitor", 0.85, "negative", 0.9, "10-K competition section"),
    ("AMD", "NVDA", "competitor", 0.85, "negative", 0.9, "10-K competition section"),
    ("AMD", "INTC", "competitor", 0.8, "negative", 0.9, "10-K competition section"),
    ("INTC", "AMD", "competitor", 0.8, "negative", 0.9, "10-K competition section"),
    ("QCOM", "AVGO", "competitor", 0.5, "negative", 0.6, "10-K competition section"),

    # --- Foundry / equipment supply chain ---
    ("TSM", "NVDA", "supplier", 0.9, "positive", 0.9, "TSMC is primary foundry for NVIDIA GPUs"),
    ("TSM", "AMD", "supplier", 0.85, "positive", 0.9, "TSMC is primary foundry for AMD chips"),
    ("TSM", "AAPL", "supplier", 0.8, "positive", 0.85, "TSMC fabricates Apple Silicon"),
    ("NVDA", "TSM", "customer", 0.9, "positive", 0.9, "NVIDIA is a major TSMC customer"),
    ("AMD", "TSM", "customer", 0.85, "positive", 0.9, "AMD is a major TSMC customer"),
    ("AAPL", "TSM", "customer", 0.8, "positive", 0.85, "Apple is TSMC's largest customer"),
    ("ASML", "TSM", "supplier", 0.9, "positive", 0.9, "ASML EUV lithography systems critical to TSMC"),
    ("ASML", "INTC", "supplier", 0.6, "positive", 0.75, "ASML supplies lithography systems to Intel fabs"),
    ("TSM", "ASML", "customer", 0.9, "positive", 0.9, "TSMC is ASML's largest customer"),

    # --- Payments / financial competitors ---
    ("V", "MA", "competitor", 0.85, "negative", 0.9, "10-K competition section, card networks"),
    ("MA", "V", "competitor", 0.85, "negative", 0.9, "10-K competition section, card networks"),
    ("PYPL", "V", "competitor", 0.4, "negative", 0.5, "Overlap in digital payments"),
    ("COIN", "PYPL", "competitor", 0.25, "negative", 0.4, "Overlap in crypto/payments rails"),
    ("JPM", "BAC", "competitor", 0.6, "negative", 0.7, "Diversified bank competitors"),
    ("BAC", "JPM", "competitor", 0.6, "negative", 0.7, "Diversified bank competitors"),

    # --- Consumer staples competitors ---
    ("KO", "PEP", "competitor", 0.85, "negative", 0.9, "10-K competition section, beverages"),
    ("PEP", "KO", "competitor", 0.85, "negative", 0.9, "10-K competition section, beverages"),
    ("WMT", "COST", "competitor", 0.6, "negative", 0.75, "Discount/warehouse retail overlap"),
    ("COST", "WMT", "competitor", 0.6, "negative", 0.75, "Discount/warehouse retail overlap"),

    # --- Auto competitors ---
    ("F", "GM", "competitor", 0.75, "negative", 0.85, "10-K competition section, US auto OEMs"),
    ("GM", "F", "competitor", 0.75, "negative", 0.85, "10-K competition section, US auto OEMs"),
    ("TSLA", "GM", "competitor", 0.5, "negative", 0.6, "EV segment overlap"),
    ("TSLA", "F", "competitor", 0.5, "negative", 0.6, "EV segment overlap"),

    # --- Energy competitors + macro link ---
    ("XOM", "CVX", "competitor", 0.7, "negative", 0.8, "10-K competition section, integrated oil & gas"),
    ("CVX", "XOM", "competitor", 0.7, "negative", 0.8, "10-K competition section, integrated oil & gas"),
    ("XOM", "OXY", "sector_peer", 0.5, "positive", 0.6, "Oil & gas sector correlation"),
    ("CVX", "OXY", "sector_peer", 0.5, "positive", 0.6, "Oil & gas sector correlation"),

    # --- Sector peers (semiconductor sympathy moves) ---
    ("NVDA", "AVGO", "sector_peer", 0.5, "positive", 0.6, "Semiconductor sector correlation"),
    ("NVDA", "MU", "sector_peer", 0.5, "positive", 0.55, "Semiconductor sector correlation, memory demand"),
    ("AMD", "MU", "sector_peer", 0.4, "positive", 0.5, "Semiconductor sector correlation"),

    # --- Cloud/software peers ---
    ("MSFT", "GOOGL", "competitor", 0.6, "negative", 0.75, "Cloud infrastructure (Azure vs GCP) competition"),
    ("MSFT", "ORCL", "competitor", 0.4, "negative", 0.55, "Enterprise software / cloud overlap"),
    ("CRM", "ORCL", "competitor", 0.5, "negative", 0.6, "Enterprise CRM/applications overlap"),
    ("ADBE", "CRM", "sector_peer", 0.3, "positive", 0.4, "Enterprise SaaS sector correlation"),

    # --- Streaming/media competitors ---
    ("NFLX", "DIS", "competitor", 0.6, "negative", 0.7, "Streaming service competition"),
    ("NFLX", "SPOT", "sector_peer", 0.3, "positive", 0.4, "Consumer streaming/subscription correlation"),
    ("DIS", "NFLX", "competitor", 0.6, "negative", 0.7, "Streaming service competition"),
]

# Real macro links (asset -> macro variable, encoded as a note since macro
# variables aren't Asset rows; kept separate from the Asset-to-Asset table
# above and expressed through EventImpact.macro_relevance at event time
# instead). Left here as documentation for future ingestion of macro
# sensitivity into system_config-driven scoring.


def seed_relationships(db=None) -> tuple[int, int, int]:
    """Upsert curated relationships. Returns (created, updated, skipped)."""
    owns_session = db is None
    db = db or SessionLocal()

    created = 0
    updated = 0
    skipped = 0
    try:
        tickers_to_id = {a.ticker: a.id for a in db.query(Asset).all()}

        for source_ticker, target_ticker, rel_type, strength, direction, confidence, note in SEED_RELATIONSHIPS:
            source_id = tickers_to_id.get(source_ticker)
            target_id = tickers_to_id.get(target_ticker)
            if not source_id or not target_id:
                logger.warning(
                    "Skipping relationship %s -> %s: asset(s) not found (seed assets first)",
                    source_ticker,
                    target_ticker,
                )
                skipped += 1
                continue

            existing = (
                db.query(AssetRelationship)
                .filter(
                    AssetRelationship.source_asset_id == source_id,
                    AssetRelationship.target_asset_id == target_id,
                    AssetRelationship.relationship_type == rel_type,
                )
                .first()
            )
            if existing:
                existing.strength = strength
                existing.direction = direction
                existing.confidence = confidence
                existing.source = note
                existing.updated_at = datetime.utcnow()
                updated += 1
            else:
                db.add(
                    AssetRelationship(
                        source_asset_id=source_id,
                        target_asset_id=target_id,
                        relationship_type=rel_type,
                        strength=strength,
                        direction=direction,
                        confidence=confidence,
                        source=note,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                )
                created += 1

        db.commit()
    finally:
        if owns_session:
            db.close()

    return created, updated, skipped


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    Base.metadata.create_all(bind=engine)
    created, updated, skipped = seed_relationships()
    logger.info(
        "Relationship seed complete: %d created, %d updated, %d skipped",
        created,
        updated,
        skipped,
    )
