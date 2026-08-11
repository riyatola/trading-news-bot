"""MEXC futures WebSocket client for real-time price/volume/OI/funding
ingestion (Sprint 3).

Companion to `app.market.mexc.MEXCClient` (REST, contract metadata only).
This module owns the streaming connection: subscribe to ticker channels
for the maintained asset universe, normalize each push into a
`MarketTick`, and hand it to a caller-supplied async handler.
Reconnection/backoff is handled internally so a flaky WS connection
degrades gracefully (skipped ticks, logged reconnects) rather than
crashing the ingestion worker -- consistent with the project's
"no silent failures, no hard crashes" pattern used in
`app.workers.asset_sync`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, Sequence

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = logging.getLogger(__name__)

MEXC_CONTRACT_WS_URL = "wss://contract.mexc.com/edge"

# MEXC's contract WS expects a ping periodically or it drops the connection.
PING_INTERVAL_SECONDS = 15
PING_TIMEOUT_SECONDS = 10

# Reconnect backoff: start small, cap so we don't hammer MEXC during an
# extended outage but still recover quickly from transient drops.
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0
BACKOFF_MULTIPLIER = 2.0


@dataclass(frozen=True)
class MarketTick:
    """A single normalized ticker push from MEXC, ready to persist as a
    market_snapshots row (after resolving mexc_symbol -> asset_id)."""

    symbol: str  # normalized, e.g. "NVDAUSDT"
    price: float
    mark_price: Optional[float]
    index_price: Optional[float]
    volume_24h: Optional[float]
    open_interest: Optional[float]
    funding_rate: Optional[float]
    timestamp: datetime


TickHandler = Callable[[MarketTick], Awaitable[None]]


class MEXCWebSocketClient:
    """Streaming client for MEXC contract ticker data.

    Usage:
        client = MEXCWebSocketClient(symbols=["NVDA_USDT", "AMD_USDT"])
        await client.run(on_tick=handle_tick)  # runs until cancelled/stopped

    `run` never raises for connection-level failures -- it logs and
    reconnects with backoff indefinitely. It only returns/raises if the
    task is cancelled or `on_tick` itself raises, so a bug in the handler
    surfaces instead of being silently swallowed.
    """

    def __init__(
        self,
        symbols: Sequence[str],
        url: str = MEXC_CONTRACT_WS_URL,
        ping_interval: float = PING_INTERVAL_SECONDS,
        ping_timeout: float = PING_TIMEOUT_SECONDS,
    ):
        self._symbols = list(symbols)
        self._url = url
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._stopped = False

    def stop(self) -> None:
        """Signal the run loop to exit after the current connection ends."""
        self._stopped = True

    async def run(self, on_tick: TickHandler) -> None:
        """Connect, subscribe, and stream ticks to `on_tick` until stopped."""
        backoff = INITIAL_BACKOFF_SECONDS
        while not self._stopped:
            try:
                async with websockets.connect(
                    self._url,
                    ping_interval=self._ping_interval,
                    ping_timeout=self._ping_timeout,
                ) as ws:
                    await self._subscribe(ws)
                    backoff = INITIAL_BACKOFF_SECONDS  # reset after a clean connect
                    async for raw_message in ws:
                        tick = self._parse_message(raw_message)
                        if tick is not None:
                            await on_tick(tick)
                    logger.info("MEXC WebSocket closed cleanly, reconnecting")
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                logger.warning(
                    "MEXC WebSocket connection lost, reconnecting in %.1fs: %s",
                    backoff,
                    exc,
                )
            except Exception:
                # Anything unexpected in the connection lifecycle (not the
                # handler itself, which is allowed to propagate) -- log
                # and retry rather than crash the whole ingestion worker.
                logger.exception("Unexpected MEXC WebSocket error, reconnecting")

            if self._stopped:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECONDS)

    async def _subscribe(self, ws) -> None:
        for symbol in self._symbols:
            await ws.send(json.dumps({"method": "sub.ticker", "param": {"symbol": symbol}}))
        logger.info("Subscribed to %d MEXC ticker channels", len(self._symbols))

    @staticmethod
    def _parse_message(raw_message: str) -> Optional[MarketTick]:
        """Parse one WS text frame into a MarketTick, or None for
        non-ticker frames (pong, subscribe ack, etc.) or malformed data."""
        try:
            payload = json.loads(raw_message)
        except (ValueError, TypeError):
            logger.warning("Discarding non-JSON MEXC WS frame")
            return None

        if not isinstance(payload, dict) or payload.get("channel") != "push.ticker":
            return None

        data = payload.get("data")
        if not isinstance(data, dict):
            return None

        symbol = data.get("symbol")
        price = data.get("lastPrice")
        if not symbol or price is None:
            logger.warning("Discarding MEXC ticker push missing symbol/price")
            return None

        try:
            ts_ms = data.get("timestamp") or payload.get("ts")
            timestamp = (
                datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                if ts_ms
                else datetime.now(timezone.utc)
            )
            return MarketTick(
                symbol=symbol.replace("_", "").replace("-", "").upper(),
                price=float(price),
                mark_price=float(data["fairPrice"]) if data.get("fairPrice") is not None else None,
                index_price=float(data["indexPrice"]) if data.get("indexPrice") is not None else None,
                volume_24h=float(data["volume24"]) if data.get("volume24") is not None else None,
                open_interest=float(data["holdVol"]) if data.get("holdVol") is not None else None,
                funding_rate=float(data["fundingRate"]) if data.get("fundingRate") is not None else None,
                timestamp=timestamp.replace(tzinfo=None),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Discarding malformed MEXC ticker push: %s", exc)
            return None
