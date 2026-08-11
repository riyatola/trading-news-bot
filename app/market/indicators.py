"""Market indicator calculations (Sprint 3).

Given a rolling history of `market_snapshots` for an asset, compute the
derived indicators stored on `MarketSnapshot.indicators` (JSON): returns
over standard horizons, relative volume, short-window volatility,
momentum, and drawdown from the recent high.

Kept as pure functions operating on plain (timestamp, price, volume)
history so they're easy to unit test without a live DB. Called by
`app.workers.market_ingestion` with history pulled from `market_snapshots`.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

# Standard return horizons tracked on every snapshot.
RETURN_HORIZONS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# Window used for the short-term realized-volatility figure (stdev of
# consecutive returns) and for the relative-volume comparison.
VOLATILITY_WINDOW = timedelta(hours=1)
RELATIVE_VOLUME_WINDOW = timedelta(hours=24)
DRAWDOWN_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class PricePoint:
    """A single historical (timestamp, price, volume) observation."""

    timestamp: datetime
    price: float
    volume_1h: Optional[float] = None


def _nearest_at_or_before(history: Sequence[PricePoint], target: datetime) -> Optional[PricePoint]:
    """Return the most recent history point at or before `target`.

    `history` is assumed sorted ascending by timestamp; this is a linear
    scan, which is fine given the small per-asset snapshot histories
    (a few thousand rows at most for the horizons tracked here).
    """
    candidate: Optional[PricePoint] = None
    for point in history:
        if point.timestamp <= target:
            candidate = point
        else:
            break
    return candidate


def calculate_return(current_price: float, past_price: Optional[float]) -> Optional[float]:
    """Percent change from `past_price` to `current_price`, or None if
    there's no valid baseline (missing history or zero price)."""
    if not past_price:
        return None
    return round((current_price - past_price) / past_price * 100, 4)


def calculate_returns(
    current_price: float,
    current_time: datetime,
    history: Sequence[PricePoint],
) -> dict[str, Optional[float]]:
    """Compute percent returns over each horizon in RETURN_HORIZONS.

    `history` must be sorted ascending by timestamp and should NOT
    include the current point.
    """
    returns: dict[str, Optional[float]] = {}
    for label, delta in RETURN_HORIZONS.items():
        target = current_time - delta
        baseline = _nearest_at_or_before(history, target)
        returns[label] = calculate_return(current_price, baseline.price if baseline else None)
    return returns


def calculate_relative_volume(
    current_volume_1h: Optional[float],
    current_time: datetime,
    history: Sequence[PricePoint],
    window: timedelta = RELATIVE_VOLUME_WINDOW,
) -> Optional[float]:
    """Current 1h volume vs. the average 1h volume over `window` of
    history. >1.0 means volume is running hot relative to its own recent
    baseline; None if there isn't enough history to form a baseline."""
    if not current_volume_1h:
        return None

    cutoff = current_time - window
    sample = [p.volume_1h for p in history if p.timestamp >= cutoff and p.volume_1h]
    if not sample:
        return None

    avg_volume = sum(sample) / len(sample)
    if not avg_volume:
        return None
    return round(current_volume_1h / avg_volume, 4)


def calculate_volatility(
    current_price: float,
    current_time: datetime,
    history: Sequence[PricePoint],
    window: timedelta = VOLATILITY_WINDOW,
) -> Optional[float]:
    """Stdev (percent) of consecutive returns within `window`, a simple
    realized-volatility proxy. None if fewer than 3 points fall in the
    window (stdev of <2 return observations is meaningless)."""
    cutoff = current_time - window
    points = [p for p in history if p.timestamp >= cutoff] + [
        PricePoint(timestamp=current_time, price=current_price)
    ]
    points.sort(key=lambda p: p.timestamp)

    if len(points) < 3:
        return None

    consecutive_returns = []
    for prev, curr in zip(points, points[1:]):
        r = calculate_return(curr.price, prev.price)
        if r is not None:
            consecutive_returns.append(r)

    if len(consecutive_returns) < 2:
        return None

    return round(statistics.stdev(consecutive_returns), 4)


def calculate_momentum(returns: dict[str, Optional[float]]) -> Optional[float]:
    """Simple momentum score: 1h return vs. the 24h return's hourly pace.
    Positive means the recent move is accelerating in the same direction
    as the daily trend; negative means it's decelerating or reversing.
    None if either input return is unavailable."""
    short = returns.get("1h")
    long_ = returns.get("24h")
    if short is None or long_ is None:
        return None
    return round(short - (long_ / 24), 4)


def calculate_drawdown(
    current_price: float,
    current_time: datetime,
    history: Sequence[PricePoint],
    window: timedelta = DRAWDOWN_WINDOW,
) -> Optional[float]:
    """Percent below the highest price observed in `window` (0 = at the
    high, negative = below it). None if there's no history in the
    window."""
    cutoff = current_time - window
    prices = [p.price for p in history if p.timestamp >= cutoff]
    prices.append(current_price)
    if len(prices) < 2:
        return None

    peak = max(prices)
    if not peak:
        return None
    return round((current_price - peak) / peak * 100, 4)


def compute_indicators(
    current_price: float,
    current_time: datetime,
    current_volume_1h: Optional[float],
    history: Sequence[PricePoint],
) -> dict:
    """Compute the full indicator set stored in `MarketSnapshot.indicators`.

    `history` is the asset's prior snapshots (any order), NOT including
    the point currently being computed.
    """
    history = sorted(history, key=lambda p: p.timestamp)
    returns = calculate_returns(current_price, current_time, history)

    return {
        "returns": returns,
        "relative_volume_24h": calculate_relative_volume(current_volume_1h, current_time, history),
        "volatility_1h": calculate_volatility(current_price, current_time, history),
        "momentum": calculate_momentum(returns),
        "drawdown_7d": calculate_drawdown(current_price, current_time, history),
    }
