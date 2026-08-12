"""Seed the `sources` table with Sprint 4's source types and their static
credibility tiers (regulator/IR ~0.9, wire service ~0.8, analyst ~0.6,
social ~0.3 per the project's credibility cold-start plan -- see
app.workers.news_ingestion for where these defaults are also applied if a
Source gets auto-created before this script runs).

Company IR RSS feed URLs are seeded as `SourceAccount` rows once known
per company -- see COMPANY_IR_FEEDS below (empty by default; fill in as
feeds are identified for tracked companies, then re-run this script).

Usage:
    python -m scripts.seed_sources
"""
from __future__ import annotations

import logging

from app.db.database import SessionLocal, engine
from app.db.models import Base, Source, SourceAccount

logger = logging.getLogger(__name__)

# (name, source_type, credibility_tier, credibility_score, description)
# Sprint 7 + Aug-2026 reality: X (Twitter) is DEPRECATED. StockTwits closed
# new developer signups (api.stocktwits.com/developers). Quiver Quantitative
# is now paid-only (~$30/mo). New recommended free/actually-signup-able
# social stack: Finnhub Social Sentiment + ApeWisdom + Reddit.
#
# Ordering mirrors _build_default_adapters() in app/workers/news_ingestion.py.
SEED_SOURCES: list[tuple[str, str, int, float, str]] = [
    ("Finnhub", "news", 2, 0.75, "Ticker-scoped company news via Finnhub.io company-news API"),
    # Finnhub Social: free tier on your existing FINNHUB_API_KEY. Same 60
    # req/min pool as the company-news endpoint, 1 extra req/ticker per poll.
    # Emits per-ticker Reddit + X mention counts + a weighted -1..1 sentiment.
    ("Finnhub Social", "news_social", 3, 0.55,
     "Aggregated Reddit + X mention counts and weighted sentiment score (-1..1) "
     "via Finnhub /stock/social-sentiment endpoint. $0 extra cost on your "
     "existing Finnhub free 60 req/min plan. Enabled by default in system_config. "
     "1 extra request per tracked ticker per poll cycle."),
    ("SEC EDGAR", "sec", 1, 0.9, "SEC EDGAR full-text filing search (8-K, 10-K)"),
    ("Company IR", "company_ir", 1, 0.9, "Company investor-relations RSS feeds"),
    # ApeWisdom: FREE, no signup, NO API KEY needed. Top-ranked r/wallstreetbets
    # + 4chan /biz/ mention counts with 24h rank deltas and bull/bear/SPY
    # proportions. DIRECT REPLACEMENT for direct StockTwits adapter (which is
    # closed to new signups as of Aug 2026).
    ("ApeWisdom WSB", "apewisdom", 3, 0.55,
     "r/wallstreetbets + 4chan /biz/ mention counts, 24h rank deltas, and "
     "bull/bear/SPY sentiment proportions per tracked ticker. Free, no "
     "signup, no API key required — just flip apewisdom_integration_enabled "
     "on in system_config. Replaces direct StockTwits adapter for new "
     "deployments (StockTwits closed new signups Aug 2026)."),
    # Reddit: raw posts from WSB / r/stocks / r/investing with $TICKER +
    # tracked-ticker allowlist regex extraction in the adapter.
    ("Reddit", "reddit", 3, 0.5,
     "Retail sentiment via r/wallstreetbets, r/stocks, r/investing newest-post streams. "
     "Tracked-ticker mentions extracted with $TICKER + allowlist regex in adapter. "
     "Free OAuth tier (script app): 60 req/min. Create app at reddit.com/prefs/apps."),
    # Quiver: unique regulatory signals (congress trades, Form 4 insider trades
    # parsed, WSB aggregates, Google Trends). PAID-ONLY as of Aug 2026 (~$30/mo).
    # Overall tier 2 because congress/insider signals are regulatory records.
    ("Quiver Quantitative", "quiver", 2, 0.75,
     "Congressional stock-trade disclosures (STOCK Act), corporate insider "
     "Form 4 trades (parsed with $ size / direction), WSB aggregate sentiment, "
     "and Google Trends search-attention per ticker. NOTE: Quiver is PAID-ONLY "
     "as of Aug 2026 (min ~$30/mo). Unique regulatory alpha; enable only with "
     "a valid QUIVER_QUANT_API_KEY."),
    # StockTwits: legacy. DIRECT SIGNUPS ARE CLOSED (api.stocktwits.com/developers
    # as of Aug 2026). Adapter still works if you have a legacy token; otherwise
    # use ApeWisdom + Finnhub Social for free equivalents.
    ("StockTwits", "stocktwits", 3, 0.6,
     "Ticker-scoped finance social streams with native Bullish/Bearish tags. "
     "LEGACY: StockTwits closed NEW developer signups as of Aug 2026. Only "
     "enable if you already have a legacy STOCKTWITS_ACCESS_TOKEN. New "
     "deployments: use ApeWisdom + Finnhub Social instead."),
]

# (company_name, account_name, rss_feed_url) -- fill in as IR feeds are
# identified for tracked companies. Left empty at launch; the news
# ingestion worker simply skips the CompanyIRAdapter until entries exist
# here (see app.workers.news_ingestion._build_default_adapters).
COMPANY_IR_FEEDS: list[tuple[str, str, str]] = []


def seed_sources(db=None) -> tuple[int, int]:
    """Upsert the seed sources (+ any configured IR feeds). Returns
    (created_count, updated_count) for the `sources` rows."""
    owns_session = db is None
    db = db or SessionLocal()
    created = 0
    updated = 0
    try:
        source_by_name: dict[str, Source] = {}
        for name, source_type, tier, score, description in SEED_SOURCES:
            existing = db.query(Source).filter(Source.name == name).first()
            if existing:
                existing.source_type = source_type
                existing.credibility_tier = tier
                existing.credibility_score = score
                existing.description = description
                updated += 1
                source_by_name[name] = existing
            else:
                source = Source(
                    name=name,
                    source_type=source_type,
                    credibility_tier=tier,
                    credibility_score=score,
                    description=description,
                )
                db.add(source)
                db.flush()  # populate source.id for SourceAccount FKs below
                created += 1
                source_by_name[name] = source

        db.commit()

        ir_source = source_by_name.get("Company IR")
        if ir_source and COMPANY_IR_FEEDS:
            for company_name, account_name, feed_url in COMPANY_IR_FEEDS:
                existing_account = (
                    db.query(SourceAccount)
                    .filter(SourceAccount.source_id == ir_source.id, SourceAccount.account_id == feed_url)
                    .first()
                )
                if not existing_account:
                    db.add(
                        SourceAccount(
                            source_id=ir_source.id,
                            account_id=feed_url,  # RSS URL doubles as the stable external id
                            account_name=account_name,
                            account_type="company_ir",
                            url=feed_url,
                        )
                    )
            db.commit()

    finally:
        if owns_session:
            db.close()

    return created, updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    Base.metadata.create_all(bind=engine)
    created, updated = seed_sources()
    logger.info("Source seed complete: %d created, %d updated", created, updated)
