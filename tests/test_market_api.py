"""Tests for GET /market/{ticker} (Sprint 3)."""
from datetime import datetime, timedelta

import pytest

from app.db.models import Asset, MarketSnapshot


@pytest.fixture
def seeded_asset_with_snapshots(db_session):
    asset = Asset(
        id="AST-01", ticker="NVDA", company_name="NVIDIA Corporation",
        mexc_symbol="NVDAUSDT", exchange_ticker="NASDAQ:NVDA",
        sector="Technology", industry="Semiconductors", country="US",
        currency="USD", active=True,
    )
    db_session.add(asset)
    db_session.commit()

    base = datetime(2026, 8, 11, 10, 0, 0)
    for i in range(3):
        db_session.add(
            MarketSnapshot(
                asset_id="AST-01",
                timestamp=base + timedelta(minutes=i),
                price=450.0 + i,
                volume_24h=1_000_000.0,
                indicators={"returns": {}},
            )
        )
    db_session.commit()
    return asset


class TestGetMarketData:
    def test_latest_snapshot(self, client, seeded_asset_with_snapshots):
        response = client.get("/market/NVDA")
        assert response.status_code == 200
        data = response.json()
        assert data["asset"]["ticker"] == "NVDA"
        assert data["market_confirmation_available"] is True
        assert data["latest"]["price"] == 452.0  # most recent of the 3 snapshots
        assert data["history"] == []

    def test_history_limit(self, client, seeded_asset_with_snapshots):
        response = client.get("/market/NVDA", params={"history_limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert len(data["history"]) == 2
        # most recent first
        assert data["history"][0]["price"] == 452.0
        assert data["history"][1]["price"] == 451.0

    def test_no_market_data_yet(self, client, db_session):
        asset = Asset(
            id="AST-02", ticker="AMD", company_name="Advanced Micro Devices, Inc.",
            mexc_symbol="AMDUSDT", exchange_ticker="NASDAQ:AMD",
            sector="Technology", industry="Semiconductors", country="US",
            currency="USD", active=True,
        )
        db_session.add(asset)
        db_session.commit()

        response = client.get("/market/AMD")
        assert response.status_code == 200
        data = response.json()
        assert data["market_confirmation_available"] is False
        assert data["latest"] is None

    def test_ticker_not_found(self, client, seeded_asset_with_snapshots):
        response = client.get("/market/ZZZZ")
        assert response.status_code == 404

    def test_ticker_case_insensitive(self, client, seeded_asset_with_snapshots):
        response = client.get("/market/nvda")
        assert response.status_code == 200
        assert response.json()["asset"]["ticker"] == "NVDA"
