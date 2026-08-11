"""Tests for asset management endpoints (Sprint 2)."""
import pytest
from datetime import datetime

from app.db.models import Asset, AssetRelationship


@pytest.fixture
def seeded_assets(db_session):
    """Seed a handful of assets + one relationship directly into db_session."""
    assets = [
        Asset(
            id="AST-01", ticker="NVDA", company_name="NVIDIA Corporation",
            mexc_symbol="NVDAUSDT", exchange_ticker="NASDAQ:NVDA",
            sector="Technology", industry="Semiconductors", country="US",
            currency="USD", active=True,
        ),
        Asset(
            id="AST-02", ticker="AMD", company_name="Advanced Micro Devices, Inc.",
            mexc_symbol="AMDUSDT", exchange_ticker="NASDAQ:AMD",
            sector="Technology", industry="Semiconductors", country="US",
            currency="USD", active=True,
        ),
        Asset(
            id="AST-03", ticker="XOM", company_name="Exxon Mobil Corporation",
            mexc_symbol="XOMUSDT", exchange_ticker="NYSE:XOM",
            sector="Energy", industry="Oil & Gas Integrated", country="US",
            currency="USD", active=False,
        ),
    ]
    for a in assets:
        db_session.add(a)
    db_session.commit()

    rel = AssetRelationship(
        source_asset_id="AST-01",
        target_asset_id="AST-02",
        relationship_type="competitor",
        strength=0.85,
        direction="negative",
        confidence=0.9,
        source="10-K competition section",
    )
    db_session.add(rel)
    db_session.commit()

    return assets


class TestGetAssets:
    def test_list_active_only_default(self, client, seeded_assets):
        response = client.get("/assets")
        assert response.status_code == 200
        data = response.json()
        tickers = {a["ticker"] for a in data["data"]}
        assert "NVDA" in tickers
        assert "AMD" in tickers
        assert "XOM" not in tickers  # inactive, excluded by default
        assert data["total"] == 2

    def test_list_including_inactive(self, client, seeded_assets):
        response = client.get("/assets", params={"active_only": False})
        assert response.status_code == 200
        data = response.json()
        tickers = {a["ticker"] for a in data["data"]}
        assert "XOM" in tickers
        assert data["total"] == 3

    def test_filter_by_sector(self, client, seeded_assets):
        response = client.get("/assets", params={"sector": "Technology"})
        data = response.json()
        assert all(a["sector"] == "Technology" for a in data["data"])
        assert data["total"] == 2

    def test_pagination(self, client, seeded_assets):
        response = client.get("/assets", params={"skip": 1, "limit": 1})
        data = response.json()
        assert len(data["data"]) == 1
        assert data["skip"] == 1
        assert data["limit"] == 1


class TestGetAsset:
    def test_get_asset_by_ticker(self, client, seeded_assets):
        response = client.get("/assets/NVDA")
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "NVDA"
        assert data["company_name"] == "NVIDIA Corporation"
        assert data["mexc_symbol"] == "NVDAUSDT"

    def test_get_asset_case_insensitive(self, client, seeded_assets):
        response = client.get("/assets/nvda")
        assert response.status_code == 200
        assert response.json()["ticker"] == "NVDA"

    def test_get_asset_not_found(self, client, seeded_assets):
        response = client.get("/assets/ZZZZ")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestGetAssetRelationships:
    def test_get_relationships(self, client, seeded_assets):
        response = client.get("/assets/NVDA/relationships")
        assert response.status_code == 200
        data = response.json()
        assert data["asset"]["ticker"] == "NVDA"
        assert len(data["relationships"]) == 1
        rel = data["relationships"][0]
        assert rel["target_ticker"] == "AMD"
        assert rel["relationship_type"] == "competitor"

    def test_filter_by_relationship_type(self, client, seeded_assets):
        response = client.get(
            "/assets/NVDA/relationships", params={"relationship_type": "supplier"}
        )
        assert response.status_code == 200
        assert response.json()["relationships"] == []

    def test_relationships_asset_not_found(self, client, seeded_assets):
        response = client.get("/assets/ZZZZ/relationships")
        assert response.status_code == 404
