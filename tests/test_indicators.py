"""Tests for app.market.indicators."""
from datetime import datetime, timedelta

from app.market.indicators import (
    PricePoint,
    calculate_drawdown,
    calculate_momentum,
    calculate_relative_volume,
    calculate_return,
    calculate_returns,
    calculate_volatility,
    compute_indicators,
)

NOW = datetime(2026, 8, 11, 12, 0, 0)


def test_calculate_return_basic():
    assert calculate_return(110, 100) == 10.0


def test_calculate_return_no_baseline():
    assert calculate_return(110, None) is None
    assert calculate_return(110, 0) is None


def test_calculate_returns_picks_nearest_at_or_before():
    # Ascending by timestamp: 25h ago, 2h ago, 10m ago.
    history = [
        PricePoint(timestamp=NOW - timedelta(hours=25), price=90),
        PricePoint(timestamp=NOW - timedelta(hours=2), price=95),
        PricePoint(timestamp=NOW - timedelta(minutes=10), price=98),
    ]
    returns = calculate_returns(current_price=100, current_time=NOW, history=history)

    # 5m/15m targets: nearest point at-or-before is the 10m-ago / 2h-ago point.
    assert returns["5m"] == calculate_return(100, 98)
    assert returns["15m"] == calculate_return(100, 95)
    # 4h/24h targets: only the 25h-ago point is old enough to qualify.
    assert returns["4h"] == calculate_return(100, 90)
    assert returns["24h"] == calculate_return(100, 90)


def test_calculate_returns_missing_horizon_is_none():
    history = [PricePoint(timestamp=NOW - timedelta(minutes=1), price=99)]
    returns = calculate_returns(current_price=100, current_time=NOW, history=history)
    assert returns["30d"] is None


def test_calculate_relative_volume():
    history = [
        PricePoint(timestamp=NOW - timedelta(hours=1), price=100, volume_1h=1000),
        PricePoint(timestamp=NOW - timedelta(hours=2), price=100, volume_1h=1000),
    ]
    rel = calculate_relative_volume(current_volume_1h=2000, current_time=NOW, history=history)
    assert rel == 2.0


def test_calculate_relative_volume_no_history():
    assert calculate_relative_volume(current_volume_1h=2000, current_time=NOW, history=[]) is None


def test_calculate_relative_volume_no_current_volume():
    history = [PricePoint(timestamp=NOW - timedelta(hours=1), price=100, volume_1h=1000)]
    assert calculate_relative_volume(current_volume_1h=None, current_time=NOW, history=history) is None


def test_calculate_volatility_needs_min_points():
    assert calculate_volatility(100, NOW, []) is None


def test_calculate_volatility_computes_stdev_of_returns():
    history = [
        PricePoint(timestamp=NOW - timedelta(minutes=40), price=100),
        PricePoint(timestamp=NOW - timedelta(minutes=20), price=105),
    ]
    vol = calculate_volatility(current_price=95, current_time=NOW, history=history)
    assert vol is not None
    assert vol > 0


def test_calculate_momentum_requires_both_horizons():
    assert calculate_momentum({"1h": None, "24h": 1.0}) is None
    assert calculate_momentum({"1h": 1.0, "24h": None}) is None
    assert calculate_momentum({"1h": 2.0, "24h": 24.0}) == 1.0


def test_calculate_drawdown_at_new_high():
    history = [PricePoint(timestamp=NOW - timedelta(days=1), price=90)]
    dd = calculate_drawdown(current_price=100, current_time=NOW, history=history)
    assert dd == 0.0


def test_calculate_drawdown_below_recent_high():
    history = [PricePoint(timestamp=NOW - timedelta(days=1), price=120)]
    dd = calculate_drawdown(current_price=100, current_time=NOW, history=history)
    assert dd == calculate_return(100, 120)


def test_calculate_drawdown_no_history():
    assert calculate_drawdown(current_price=100, current_time=NOW, history=[]) is None


def test_compute_indicators_shape():
    history = [PricePoint(timestamp=NOW - timedelta(hours=1), price=95, volume_1h=500)]
    result = compute_indicators(
        current_price=100, current_time=NOW, current_volume_1h=600, history=history
    )
    assert set(result.keys()) == {
        "returns", "relative_volume_24h", "volatility_1h", "momentum", "drawdown_7d",
    }
    assert set(result["returns"].keys()) == {"5m", "15m", "1h", "4h", "24h", "7d", "30d"}
