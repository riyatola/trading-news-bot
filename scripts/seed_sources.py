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
SEED_SOURCES: list[tuple[str, str, int, float, str]] = [
    ("NewsAPI", "news", 2, 0.75, "Aggregated wire/publisher news via NewsAPI.org"),
    ("SEC EDGAR", "sec", 1, 0.9, "SEC EDGAR full-text filing search (8-K, 10-K)"),
    ("Company IR", "company_ir", 1, 0.9, "Company investor-relations RSS feeds"),
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
