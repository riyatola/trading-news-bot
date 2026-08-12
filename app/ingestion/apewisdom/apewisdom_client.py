"""ApeWisdom API client (Sprint 7: retail WSB + 4chan mention counts).

ApeWisdom aggregates the most-mentioned tickers on Reddit r/wallstreetbets
and 4chan /biz/ into a live, free-to-query JSON API. No API key required,
no signup, no rate limits published (we self-throttle to 1 req/sec to be
courteous). Endpoint returns the top-N most discussed tickers ranked by
mention count with per-ticker sentiment (bull/bear/spy proportions), 24h
rank change, and price data.

This replaces the original direct-StockTwits plan (StockTwits closed new
developer signups in 2026 per api.stocktwits.com/developers) and overlaps
nicely with Quiver's WSB endpoint (which is now paid-only). Combined with
Finnhub Social Sentiment (also free on the existing 60 req/min plan) and
the raw Reddit adapter (r/wallstreetbets + r/stocks + r/investing posts),
this gives us 3 complementary retail-sentiment signals for $0:

  * RedditAdapter         -> raw, full-text r/wallstreetbets posts (LLM scored)
  * Finnhub social (new)  -> Reddit + X mention counts + sentiment (-1..1)
  * ApeWisdom             -> WSB + 4chan top-mentioned tickers (no API key)

Endpoints covered:
  * GET https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}
    -> all tracked tickers, paginated (returns 50 per page by default)
  * GET https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/{page}
    -> WSB only (the signal your alert system cares most about)

The client fetches N pages of WSB results, then cross-references the
response against our tracked ticker universe to produce ApeWisdomTicker
rows. Untracked tickers are dropped at the client layer so the adapter
receives only relevant rows.

Mirrors the same error-handling shape as every other ingestion client:
network/rate/shape failures raise ApeWisdomAPIError so the adapter/worker
can apply consistent retry/dead-letter handling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.exceptions import ApeWisdomAPIError

logger = logging.getLogger(__name__)

APEWISDOM_BASE = "https://apewisdom.io/api/v1.0/filter"
DEFAULT_FILTER = "wallstreetbets"  # WSB is the high-signal feed for this bot
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_PAGES = 3  # top 150 WSB tickers; covers all 52 tracked names easily
# Self-throttle: ApeWisdom doesn't publish a rate limit, so we stay polite.
INTER_REQUEST_PAUSE_SECONDS = 1.0


@dataclass(frozen=True)
class ApeWisdomTicker:
    """One ranked ticker + mention counts from an ApeWisdom page."""

    ticker: str
    rank: int
    mentions: int
    mention_24h_ago: int
    rank_24h_ago: Optional[int]
    upvotes: int
    sentiment_bull: float  # 0..1 proportion
    sentiment_bear: float  # 0..1 proportion
    sentiment_spy: float   # 0..1 proportion (short of SPY / market-hedged)
    fetched_at: datetime


class ApeWisdomClient:
    def __init__(
        self,
        base_url: str = APEWISDOM_BASE,
        default_filter: str = DEFAULT_FILTER,
        default_pages: int = DEFAULT_PAGES,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._base = base_url.rstrip("/")
        self._default_filter = default_filter
        self._default_pages = max(1, int(default_pages))
        self._timeout = timeout
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def __aenter__(self) -> "ApeWisdomClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _to_float(v: object, default: float = 0.0) -> float:
        try:
            f = float(v)
            if f < 0:
                return 0.0
            if f > 1:
                return 1.0
            return f
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_int(v: object, default: int = 0) -> int:
        try:
            i = int(v)
            return i if i >= 0 else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_opt_int(v: object) -> Optional[int]:
        try:
            i = int(v)
            return i if i >= 0 else None
        except (TypeError, ValueError):
            return None

    async def _fetch_page(self, filter_name: str, page: int) -> list[dict]:
        url = f"{self._base}/{filter_name}/page/{page}"
        try:
            response = await self._client.get(url, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise ApeWisdomAPIError(
                f"ApeWisdom request failed for filter={filter_name} page={page}: {exc}"
            ) from exc

        if response.status_code == 429:
            raise ApeWisdomAPIError("ApeWisdom rate limit exceeded (429)")
        if response.status_code == 404:
            logger.warning(
                "ApeWisdom returned 404 for filter=%s page=%s (filter name changed?)",
                filter_name, page,
            )
            return []
        if response.status_code != 200:
            raise ApeWisdomAPIError(
                f"ApeWisdom returned status {response.status_code} for "
                f"filter={filter_name} page={page}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApeWisdomAPIError(
                f"ApeWisdom returned invalid JSON for filter={filter_name} page={page}"
            ) from exc

        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            logger.warning(
                "ApeWisdom returned unexpected results shape for filter=%s "
                "page=%s; skipping page", filter_name, page
            )
            return []
        return results

    async def fetch_mentions(
        self,
        tracked_tickers: list[str],
        filter_name: Optional[str] = None,
        pages: Optional[int] = None,
    ) -> list[ApeWisdomTicker]:
        """Fetch ranked tickers from ApeWisdom, filter to `tracked_tickers`.

        Only tickers present (uppercase) in `tracked_tickers` are returned.
        Pulls `pages` pages of results; defaults to the client constructor
        value (3 pages = top 150 WSB tickers, plenty to cover the 52-ticker
        tracked universe).
        """
        if not tracked_tickers:
            return []
        tracked_upper = {t.upper() for t in tracked_tickers}
        filter_name = filter_name or self._default_filter
        pages = max(1, int(pages) if pages is not None else self._default_pages)

        fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        all_items: list[ApeWisdomTicker] = []

        import asyncio
        for page in range(1, pages + 1):
            raw = await self._fetch_page(filter_name, page)
            if not raw:
                break
            for item in raw:
                ticker_raw = str(item.get("ticker") or "").strip().upper()
                if not ticker_raw or ticker_raw not in tracked_upper:
                    continue

                all_items.append(
                    ApeWisdomTicker(
                        ticker=ticker_raw,
                        rank=self._to_int(item.get("rank")),
                        mentions=self._to_int(item.get("mentions")),
                        mention_24h_ago=self._to_int(item.get("mentions_24h_ago")),
                        rank_24h_ago=self._to_opt_int(item.get("rank_24h_ago")),
                        upvotes=self._to_int(item.get("upvotes")),
                        sentiment_bull=self._to_float(item.get("sentiment_bullish")),
                        sentiment_bear=self._to_float(item.get("sentiment_bearish")),
                        sentiment_spy=self._to_float(item.get("sentiment_spy_put")),
                        fetched_at=fetched_at,
                    )
                )
            # Polite pause between pages; ApeWisdom is a community-run free service.
            if page < pages:
                await asyncio.sleep(INTER_REQUEST_PAUSE_SECONDS)

        logger.info(
            "Fetched %d tracked-ticker rows from ApeWisdom (%s, %d pages)",
            len(all_items), filter_name, pages,
        )
        return all_items
