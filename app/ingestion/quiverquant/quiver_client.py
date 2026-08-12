"""Quiver Quantitative API client (Sprint 7: regulatory/insider signals).

Covers 4 complementary signal types the rest of the source stack (news,
SEC EDGAR, company IR, StockTwits, Reddit) does NOT capture:

1. **Congressional trades** (`/beta/congress/ticker/{ticker}`) -- reported
   transactions by US Congress members. These are delayed-reporting by
   design (STOCK Act reporting window), so they aren't high-frequency,
   but they carry unique alpha when the names/committees line up with
   pending legislation.

2. **Corporate insider trades** (`/beta/insiders/{ticker}`) -- Form 4
   transactions by officers / directors / 10%+ holders. EDGAR captures
   the filing text eventually, but Quiver's endpoint returns them
   pre-parsed with ticker + direction + dollar size ready to use.

3. **WSB historical sentiment** (`/beta/social/wsb/{ticker}`) -- Quiver
   already runs their own WSB sentiment aggregator per ticker. We keep
   our own Reddit/StockTwits ingestion for raw-post evidence, but this
   is a useful free cross-check / pre-computed sentiment signal.

4. **Google Trends** (`/beta/historical/gt/{ticker}`) -- search-volume
   changes per ticker; different signal axis (retail attention rather
   than sentiment).

All 4 endpoints are ticker-scoped, consistent with FinnhubClient and
StockTwitsClient, and a free tier covers the basic endpoints.

Mirrors the same error-handling shape: network/rate/shape failures raise
`QuiverQuantAPIError` for the adapter/worker's consistent retry/dead-
letter handling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import httpx

from app.exceptions import QuiverQuantAPIError

logger = logging.getLogger(__name__)

QUIVER_BASE_URL = "https://api.quiverquant.com/beta"
DEFAULT_TIMEOUT_SECONDS = 15.0
FREE_TIER_HEADERS = {"Accept": "application/json"}
# Congressional + insider trades are relatively low-volume (a few per
# ticker per month at most), so 90 days is a comfortable lookback on
# cold start without wasting rate budget.
DEFAULT_LOOKBACK_DAYS = 90
# A single poll hits 4 endpoints per ticker -- on a 52-ticker universe
# that's 208 requests/poll. To stay within the free tier's implicit
# budget we cap the number of tickers we hit per poll and rely on the
# `since` watermark to pick up deltas on subsequent cycles.
MAX_TICKERS_PER_POLL = 12


@dataclass(frozen=True)
class QuiverCongressTrade:
    ticker: str
    report_date: datetime
    transaction_date: datetime
    representative: str
    transaction_type: str  # "Purchase" / "Sale"
    amount_range: str  # Quiver returns a dollar range string, not exact
    description: str


@dataclass(frozen=True)
class QuiverInsiderTrade:
    ticker: str
    report_date: datetime
    transaction_date: datetime
    insider_name: str
    insider_title: str
    transaction_type: str
    shares: int
    last_price: Optional[float]
    d_value: Optional[float]  # change in holdings value


@dataclass(frozen=True)
class QuiverWSBSentiment:
    ticker: str
    date: datetime
    mentions: int
    sentiment: float  # -1..1 range, per Quiver's docs
    rank: Optional[int]


@dataclass(frozen=True)
class QuiverGoogleTrend:
    ticker: str
    date: datetime
    search_interest: int  # relative 0..100 scale, per Google Trends definition


@dataclass(frozen=True)
class QuiverBatch:
    congress_trades: list[QuiverCongressTrade]
    insider_trades: list[QuiverInsiderTrade]
    wsb_sentiment: list[QuiverWSBSentiment]
    google_trends: list[QuiverGoogleTrend]


class QuiverQuantClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = QUIVER_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client  # injectable for testing

    # --- helpers -----------------------------------------------------

    def _headers(self) -> dict:
        headers = dict(FREE_TIER_HEADERS)
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _get_json(self, path: str, params: Optional[dict] = None) -> object:
        url = f"{self._base_url}{path}"
        try:
            if self._client is not None:
                response = await self._client.get(
                    url, params=params, headers=self._headers(), timeout=self._timeout
                )
            else:
                async with httpx.AsyncClient() as http:
                    response = await http.get(
                        url, params=params, headers=self._headers(), timeout=self._timeout
                    )
        except httpx.HTTPError as exc:
            raise QuiverQuantAPIError(f"Quiver request failed for {path}: {exc}") from exc

        if response.status_code == 429:
            raise QuiverQuantAPIError("Quiver Quantitative rate limit exceeded (429)")
        if response.status_code == 401:
            raise QuiverQuantAPIError(
                "Quiver returned 401 Unauthorized -- check API_KEY or confirm the endpoint is on your tier"
            )
        if response.status_code != 200:
            raise QuiverQuantAPIError(
                f"Quiver returned status {response.status_code} for {path}: {response.text[:200]}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise QuiverQuantAPIError(f"Quiver returned invalid JSON for {path}") from exc

    @staticmethod
    def _parse_date(val: object, fallback: Optional[date] = None) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            try:
                return datetime.fromtimestamp(float(val), tz=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError, OSError):
                return None
        s = str(val)
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=None)
            except ValueError:
                continue
        if fallback is not None:
            return datetime.combine(fallback, datetime.min.time())
        return None

    # --- endpoints ---------------------------------------------------

    async def _fetch_congress_trades(self, ticker: str, since: Optional[datetime]) -> list[QuiverCongressTrade]:
        data = await self._get_json(f"/congress/ticker/{ticker}")
        results: list[QuiverCongressTrade] = []
        if not isinstance(data, list):
            return results
        for item in data:
            rep_date = self._parse_date(item.get("ReportDate"))
            tx_date = self._parse_date(item.get("TransactionDate"))
            if since is not None:
                compare = rep_date or tx_date
                if compare is None or compare < since:
                    continue
            t_type = str(item.get("Transaction") or "").strip()
            if t_type.lower().startswith("pur"):
                t_type = "Purchase"
            elif t_type.lower().startswith("sal"):
                t_type = "Sale"
            representative = str(item.get("Representative") or item.get("Name") or "")
            results.append(
                QuiverCongressTrade(
                    ticker=ticker,
                    report_date=rep_date or datetime.utcnow(),
                    transaction_date=tx_date or rep_date or datetime.utcnow(),
                    representative=representative,
                    transaction_type=t_type or "Unknown",
                    amount_range=str(item.get("Amount") or ""),
                    description=str(item.get("Description") or item.get("House") or ""),
                )
            )
        return results

    async def _fetch_insider_trades(self, ticker: str, since: Optional[datetime]) -> list[QuiverInsiderTrade]:
        data = await self._get_json(f"/insiders/{ticker}")
        results: list[QuiverInsiderTrade] = []
        if not isinstance(data, list):
            return results
        for item in data:
            rep_date = self._parse_date(item.get("ReportDate"))
            tx_date = self._parse_date(item.get("X"))  # Quiver API uses column "X" for tx date on this endpoint
            if since is not None:
                compare = rep_date or tx_date
                if compare is None or compare < since:
                    continue
            shares = item.get("Shares")
            try:
                shares_int = int(shares) if shares is not None else 0
            except (TypeError, ValueError):
                shares_int = 0
            try:
                last_price = float(item.get("LastPrice")) if item.get("LastPrice") is not None else None
            except (TypeError, ValueError):
                last_price = None
            try:
                d_value = float(item.get("DollarValue")) if item.get("DollarValue") is not None else None
            except (TypeError, ValueError):
                d_value = None
            t_type = str(item.get("TransactionType") or "").strip()
            results.append(
                QuiverInsiderTrade(
                    ticker=ticker,
                    report_date=rep_date or datetime.utcnow(),
                    transaction_date=tx_date or rep_date or datetime.utcnow(),
                    insider_name=str(item.get("Name") or ""),
                    insider_title=str(item.get("Title") or ""),
                    transaction_type=t_type or "Unknown",
                    shares=shares_int,
                    last_price=last_price,
                    d_value=d_value,
                )
            )
        return results

    async def _fetch_wsb_sentiment(self, ticker: str, since: Optional[datetime]) -> list[QuiverWSBSentiment]:
        data = await self._get_json(f"/social/wsb/{ticker}")
        results: list[QuiverWSBSentiment] = []
        if not isinstance(data, list):
            return results
        for item in data:
            d = self._parse_date(item.get("Date"))
            if d is None:
                continue
            if since is not None and d < since:
                continue
            try:
                mentions = int(item.get("Mentions") or 0)
            except (TypeError, ValueError):
                mentions = 0
            try:
                sentiment = float(item.get("Sentiment") or 0)
            except (TypeError, ValueError):
                sentiment = 0.0
            try:
                rank = int(item.get("Rank")) if item.get("Rank") is not None else None
            except (TypeError, ValueError):
                rank = None
            # Ignore rows with 0 mentions -- they're placeholders
            if mentions <= 0:
                continue
            results.append(
                QuiverWSBSentiment(
                    ticker=ticker, date=d, mentions=mentions, sentiment=sentiment, rank=rank
                )
            )
        # Keep only the most recent 5 per ticker to avoid flooding
        return sorted(results, key=lambda r: r.date, reverse=True)[:5]

    async def _fetch_google_trends(self, ticker: str, since: Optional[datetime]) -> list[QuiverGoogleTrend]:
        data = await self._get_json(f"/historical/gt/{ticker}")
        results: list[QuiverGoogleTrend] = []
        if not isinstance(data, list):
            return results
        for item in data:
            d = self._parse_date(item.get("Date"))
            if d is None:
                continue
            if since is not None and d < since:
                continue
            try:
                interest = int(item.get("Interest") or item.get("Search_Trend") or 0)
            except (TypeError, ValueError):
                continue
            if interest <= 0:
                continue
            results.append(QuiverGoogleTrend(ticker=ticker, date=d, search_interest=interest))
        # One row is enough -- we only care about recent jumps
        return sorted(results, key=lambda r: r.date, reverse=True)[:1]

    # --- public batch ------------------------------------------------

    async def fetch_batch(self, tickers: list[str], since: Optional[datetime] = None) -> QuiverBatch:
        if not tickers:
            return QuiverBatch([], [], [], [])

        tickers = tickers[:MAX_TICKERS_PER_POLL]
        since_effective = since or (
            datetime.utcnow() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        )

        congress: list[QuiverCongressTrade] = []
        insider: list[QuiverInsiderTrade] = []
        wsb: list[QuiverWSBSentiment] = []
        gt: list[QuiverGoogleTrend] = []

        for ticker in tickers:
            # Each endpoint is allowed to fail individually (log + skip) so
            # one deprecation/outage on a signal type doesn't dead-letter
            # the entire adapter run -- a 404 for "endpoint not on free
            # tier" is the most common cause here.
            try:
                congress.extend(await self._fetch_congress_trades(ticker, since_effective))
            except QuiverQuantAPIError as exc:
                logger.warning("Quiver congress_trades failed for %s: %s", ticker, exc)
            try:
                insider.extend(await self._fetch_insider_trades(ticker, since_effective))
            except QuiverQuantAPIError as exc:
                logger.warning("Quiver insider_trades failed for %s: %s", ticker, exc)
            try:
                wsb.extend(await self._fetch_wsb_sentiment(ticker, since_effective))
            except QuiverQuantAPIError as exc:
                logger.warning("Quiver wsb_sentiment failed for %s: %s", ticker, exc)
            try:
                gt.extend(await self._fetch_google_trends(ticker, since_effective))
            except QuiverQuantAPIError as exc:
                logger.warning("Quiver google_trends failed for %s: %s", ticker, exc)

        logger.info(
            "Quiver batch: %d congress, %d insider, %d wsb, %d trends (across %d tickers)",
            len(congress), len(insider), len(wsb), len(gt), len(tickers),
        )
        return QuiverBatch(congress_trades=congress, insider_trades=insider, wsb_sentiment=wsb, google_trends=gt)


# Import at bottom to avoid circular-style issues in editors that order
# imports on save; used only inside fetch_batch default since arg.
from datetime import timedelta  # noqa: E402
