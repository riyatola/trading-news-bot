"""Tests for app.workers.market_ingestion."""
from datetime import datetime, timedelta

import pytest

from app.db.models import Asset, MarketSnapshot
from app.market.prices import MarketTick
from app.workers.market_ingestion import (
    MIN_SNAPSHOT_INTERVAL,
    load_history,
    load_symbol_map,
    persist_tick,
    should_persist,
)


@pytest.fixture
def seeded_asset(db_session):
    asset = Asset(
        id="AST-01", ticker="NVDA", company_name="NVIDIA Corporation",
        mexc_symbol="NVDAUSDT", exchange_ticker="NASDAQ:NVDA",
        sector="Technology", industry="Semiconductors", country="US",
        currency="USD", active=True,
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def _tick(**overrides):
    defaults = dict(
        symbol="NVDAUSDT",
        price=450.0,
        mark_price=450.1,
        index_price=449.9,
        volume_24h=1_000_000.0,
        open_interest=50_000.0,
        funding_rate=0.0001,
        timestamp=datetime(2026, 8, 11, 12, 0, 0),
    )
    defaults.update(overrides)
    return MarketTick(**defaults)


def test_load_symbol_map_only_active_assets(db_session, seeded_asset):
    inactive = Asset(
        id="AST-02", ticker="XOM", company_name="Exxon Mobil Corporation",
        mexc_symbol="XOMUSDT", exchange_ticker="NYSE:XOM",
        sector="Energy", industry="Oil & Gas Integrated", country="US",
        currency="USD", active=False,
    )
    db_session.add(inactive)
    db_session.commit()

    mapping = load_symbol_map(db_session)
    assert mapping == {"NVDAUSDT": "AST-01"}


def test_persist_tick_creates_snapshot_with_indicators(db_session, seeded_asset):
    tick = _tick()
    snapshot = persist_tick(db_session, "AST-01", tick)

    assert snapshot is not None
    stored = db_session.query(MarketSnapshot).filter_by(asset_id="AST-01").first()
    assert stored is not None
    assert stored.price == 450.0
    assert stored.mark_price == 450.1
    assert "returns" in stored.indicators


def test_persist_tick_duplicate_timestamp_returns_none(db_session, seeded_asset):
    tick = _tick()
    first = persist_tick(db_session, "AST-01", tick)
    assert first is not None

    duplicate = persist_tick(db_session, "AST-01", tick)  # same asset_id + timestamp
    assert duplicate is None
    assert db_session.query(MarketSnapshot).filter_by(asset_id="AST-01").count() == 1


def test_load_history_excludes_current_point_and_out_of_window(db_session, seeded_asset):
    old_ts = datetime(2026, 8, 11, 12, 0, 0)
    persist_tick(db_session, "AST-01", _tick(timestamp=old_ts))

    later_ts = old_ts + timedelta(minutes=10)
    history = load_history(db_session, "AST-01", later_ts)
    assert len(history) == 1
    assert history[0].timestamp == old_ts

    # A snapshot at exactly `before` must not appear in its own history window.
    history_at_old = load_history(db_session, "AST-01", old_ts)
    assert history_at_old == []


def test_should_persist_throttles_within_window():
    last_persisted = {}
    t0 = datetime(2026, 8, 11, 12, 0, 0)

    assert should_persist("AST-01", t0, last_persisted) is True
    last_persisted["AST-01"] = t0

    assert should_persist("AST-01", t0 + timedelta(seconds=1), last_persisted) is False
    assert should_persist("AST-01", t0 + MIN_SNAPSHOT_INTERVAL, last_persisted) is True
