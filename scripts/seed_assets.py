"""Seed the `assets` table with the maintained 52 MEXC stock-perpetual universe.

This is the curated baseline referenced as "Appendix A" in the project
spec. Symbols/sectors below are a representative, hand-curated set of
large-cap US equities across the sectors MEXC's stock-perpetual and
tokenized-stock programs have historically targeted. The hourly
`app.workers.asset_sync.sync_assets` job reconciles this baseline against
whatever is actually live on MEXC at runtime -- it deactivates symbols that
go dark and reactivates ones that come back, without deleting history.

Usage:
    python -m scripts.seed_assets
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.db.database import SessionLocal, engine
from app.db.models import Asset, Base

logger = logging.getLogger(__name__)

# (ticker, company_name, sector, industry, exchange_ticker)
# mexc_symbol is derived as f"{ticker}USDT"; country/currency default to US/USD.
SEED_ASSETS: list[tuple[str, str, str, str, str]] = [
    ("AAPL", "Apple Inc.", "Technology", "Consumer Electronics", "NASDAQ:AAPL"),
    ("MSFT", "Microsoft Corporation", "Technology", "Software - Infrastructure", "NASDAQ:MSFT"),
    ("GOOGL", "Alphabet Inc.", "Communication Services", "Internet Content & Information", "NASDAQ:GOOGL"),
    ("AMZN", "Amazon.com, Inc.", "Consumer Discretionary", "Internet Retail", "NASDAQ:AMZN"),
    ("NVDA", "NVIDIA Corporation", "Technology", "Semiconductors", "NASDAQ:NVDA"),
    ("META", "Meta Platforms, Inc.", "Communication Services", "Internet Content & Information", "NASDAQ:META"),
    ("TSLA", "Tesla, Inc.", "Consumer Discretionary", "Auto Manufacturers", "NASDAQ:TSLA"),
    ("AVGO", "Broadcom Inc.", "Technology", "Semiconductors", "NASDAQ:AVGO"),
    ("AMD", "Advanced Micro Devices, Inc.", "Technology", "Semiconductors", "NASDAQ:AMD"),
    ("INTC", "Intel Corporation", "Technology", "Semiconductors", "NASDAQ:INTC"),
    ("QCOM", "QUALCOMM Incorporated", "Technology", "Semiconductors", "NASDAQ:QCOM"),
    ("TXN", "Texas Instruments Incorporated", "Technology", "Semiconductors", "NASDAQ:TXN"),
    ("MU", "Micron Technology, Inc.", "Technology", "Semiconductors", "NASDAQ:MU"),
    ("ASML", "ASML Holding N.V.", "Technology", "Semiconductor Equipment & Materials", "NASDAQ:ASML"),
    ("TSM", "Taiwan Semiconductor Manufacturing Co.", "Technology", "Semiconductors", "NYSE:TSM"),
    ("ORCL", "Oracle Corporation", "Technology", "Software - Infrastructure", "NYSE:ORCL"),
    ("CRM", "Salesforce, Inc.", "Technology", "Software - Application", "NYSE:CRM"),
    ("ADBE", "Adobe Inc.", "Technology", "Software - Application", "NASDAQ:ADBE"),
    ("PLTR", "Palantir Technologies Inc.", "Technology", "Software - Infrastructure", "NASDAQ:PLTR"),
    ("NFLX", "Netflix, Inc.", "Communication Services", "Entertainment", "NASDAQ:NFLX"),
    ("DIS", "The Walt Disney Company", "Communication Services", "Entertainment", "NYSE:DIS"),
    ("SPOT", "Spotify Technology S.A.", "Communication Services", "Entertainment", "NYSE:SPOT"),
    ("NKE", "NIKE, Inc.", "Consumer Discretionary", "Footwear & Accessories", "NYSE:NKE"),
    ("SBUX", "Starbucks Corporation", "Consumer Discretionary", "Restaurants", "NASDAQ:SBUX"),
    ("MCD", "McDonald's Corporation", "Consumer Discretionary", "Restaurants", "NYSE:MCD"),
    ("JPM", "JPMorgan Chase & Co.", "Financial Services", "Banks - Diversified", "NYSE:JPM"),
    ("BAC", "Bank of America Corporation", "Financial Services", "Banks - Diversified", "NYSE:BAC"),
    ("GS", "The Goldman Sachs Group, Inc.", "Financial Services", "Capital Markets", "NYSE:GS"),
    ("V", "Visa Inc.", "Financial Services", "Credit Services", "NYSE:V"),
    ("MA", "Mastercard Incorporated", "Financial Services", "Credit Services", "NYSE:MA"),
    ("PYPL", "PayPal Holdings, Inc.", "Financial Services", "Credit Services", "NASDAQ:PYPL"),
    ("COIN", "Coinbase Global, Inc.", "Financial Services", "Financial Data & Exchanges", "NASDAQ:COIN"),
    ("UNH", "UnitedHealth Group Incorporated", "Healthcare", "Healthcare Plans", "NYSE:UNH"),
    ("JNJ", "Johnson & Johnson", "Healthcare", "Drug Manufacturers - General", "NYSE:JNJ"),
    ("PFE", "Pfizer Inc.", "Healthcare", "Drug Manufacturers - General", "NYSE:PFE"),
    ("LLY", "Eli Lilly and Company", "Healthcare", "Drug Manufacturers - General", "NYSE:LLY"),
    ("MRNA", "Moderna, Inc.", "Healthcare", "Biotechnology", "NASDAQ:MRNA"),
    ("XOM", "Exxon Mobil Corporation", "Energy", "Oil & Gas Integrated", "NYSE:XOM"),
    ("CVX", "Chevron Corporation", "Energy", "Oil & Gas Integrated", "NYSE:CVX"),
    ("OXY", "Occidental Petroleum Corporation", "Energy", "Oil & Gas E&P", "NYSE:OXY"),
    ("BA", "The Boeing Company", "Industrials", "Aerospace & Defense", "NYSE:BA"),
    ("CAT", "Caterpillar Inc.", "Industrials", "Farm & Heavy Construction Machinery", "NYSE:CAT"),
    ("GE", "GE Aerospace", "Industrials", "Specialty Industrial Machinery", "NYSE:GE"),
    ("T", "AT&T Inc.", "Communication Services", "Telecom Services", "NYSE:T"),
    ("VZ", "Verizon Communications Inc.", "Communication Services", "Telecom Services", "NYSE:VZ"),
    ("KO", "The Coca-Cola Company", "Consumer Staples", "Beverages - Non-Alcoholic", "NYSE:KO"),
    ("PEP", "PepsiCo, Inc.", "Consumer Staples", "Beverages - Non-Alcoholic", "NASDAQ:PEP"),
    ("WMT", "Walmart Inc.", "Consumer Staples", "Discount Stores", "NYSE:WMT"),
    ("PG", "The Procter & Gamble Company", "Consumer Staples", "Household & Personal Products", "NYSE:PG"),
    ("COST", "Costco Wholesale Corporation", "Consumer Staples", "Discount Stores", "NASDAQ:COST"),
    ("F", "Ford Motor Company", "Consumer Discretionary", "Auto Manufacturers", "NYSE:F"),
    ("GM", "General Motors Company", "Consumer Discretionary", "Auto Manufacturers", "NYSE:GM"),
]

assert len(SEED_ASSETS) == 52, f"Expected 52 seed assets, got {len(SEED_ASSETS)}"


def seed_assets(db=None, seed_data=None) -> tuple[int, int]:
    """Upsert the seed assets. Returns (created_count, updated_count)."""
    owns_session = db is None
    db = db or SessionLocal()
    seed_data = seed_data if seed_data is not None else SEED_ASSETS

    created = 0
    updated = 0
    try:
        for idx, (ticker, company_name, sector, industry, exchange_ticker) in enumerate(seed_data, start=1):
            asset_id = f"AST-{idx:02d}"
            mexc_symbol = f"{ticker}USDT"

            existing = db.query(Asset).filter(Asset.ticker == ticker).first()
            if existing:
                existing.company_name = company_name
                existing.sector = sector
                existing.industry = industry
                existing.exchange_ticker = exchange_ticker
                existing.mexc_symbol = mexc_symbol
                existing.updated_at = datetime.utcnow()
                updated += 1
            else:
                db.add(
                    Asset(
                        id=asset_id,
                        ticker=ticker,
                        company_name=company_name,
                        mexc_symbol=mexc_symbol,
                        exchange_ticker=exchange_ticker,
                        sector=sector,
                        industry=industry,
                        country="US",
                        currency="USD",
                        active=True,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                )
                created += 1

        db.commit()
    finally:
        if owns_session:
            db.close()

    return created, updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    Base.metadata.create_all(bind=engine)
    created, updated = seed_assets()
    logger.info("Asset seed complete: %d created, %d updated", created, updated)
