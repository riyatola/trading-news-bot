"""StockTwits API v2 client (Sprint 7: social sentiment, ticker-scoped).

Uses the `/streams/symbol/{symbol}.json` endpoint, which returns the 30
most recent messages tagged with a given ticker symbol -- same
ticker-scoped query pattern as `FinnhubClient`, and a natural fit since
we already maintain a fixed 52-ticker asset universe. StockTwits' free
tier covers 200 requests/hour, comfortably covering 52 tickers polled
every few minutes.

Mirrors the error-handling shape of the other ingestion clients in the
project: network/shape/rate-limit failures raise `StockTwitsAPIError` so
the adapter + worker (`app.workers.news_ingestion`) can apply consistent
retry/dead-letter handling.

StockTwits responses optionally include `entities.sentiment.basic` with
values `Bullish` / `Bearish` directly on each message -- this is
preserved in the `sentiment` field of `StockTwitsMessage` so the
downstream LLM pre-filter/event-classifier can optionally use it with
less or zero LLM work.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.exceptions import StockTwitsAPIError

logger = logging.getLogger(__name__)

STOCKTWITS_SYMBOL_STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
DEFAULT_TIMEOUT_SECONDS = 15.0
# Free tier is 200 req/hr; 52 tickers per poll is well within budget.
# Still batch to be courteous and to respect StockTwits' implied
# per-client limits.
SYMBOLS_PER_POLL_LIMIT = 52
MAX_RESULTS_PER_SYMBOL = 30  # StockTwits default; matches API spec.


@dataclass(frozen=True)
class StockTwitsMessage:
    message_id: str
    symbol: str
    text: str
    created_at: datetime
    author_username: str
    author_name: Optional[str]
    sentiment: Optional[str]  # "Bullish" / "Bearish" / None = neutral/untagged
    url: str
    likes: int
    reshares: int


class StockTwitsClient:
    def __init__(
        self,
        access_token: str,
        base_url_template: str = STOCKTWITS_SYMBOL_STREAM_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._access_token = access_token
        self._base_url_template = base_url_template
        self._timeout = timeout
        self._client = client  # injectable for testing

    async def fetch_symbol_stream(
        self, tickers: list[str], since: Optional[datetime] = None
    ) -> list[StockTwitsMessage]:
        """Fetch the latest message stream for each of `tickers`.

        If `since` is provided, messages older than `since` are filtered
        out client-side (StockTwits' `/streams/symbol` endpoint only
        supports returning the tail of the stream, not an explicit
        `since` parameter).

        Raises:
            StockTwitsAPIError: on missing token, network failure, rate
                limiting, non-200 response, or an unexpected response
                shape.
        """
        if not self._access_token:
            raise StockTwitsAPIError("StockTwits request skipped: no access token configured")
        if not tickers:
            return []

        tickers = tickers[:SYMBOLS_PER_POLL_LIMIT]
        params: dict = {"access_token": self._access_token}
        all_messages: list[StockTwitsMessage] = []

        for ticker in tickers:
            url = self._base_url_template.format(symbol=ticker)
            try:
                if self._client is not None:
                    response = await self._client.get(url, params=params, timeout=self._timeout)
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(url, params=params, timeout=self._timeout)
            except httpx.HTTPError as exc:
                raise StockTwitsAPIError(f"StockTwits request failed for '{ticker}': {exc}") from exc

            if response.status_code == 429:
                raise StockTwitsAPIError("StockTwits rate limit exceeded (429)")
            if response.status_code == 404:
                logger.warning("StockTwits returned 404 for symbol '%s' (unknown or not tracked)", ticker)
                continue
            if response.status_code != 200:
                raise StockTwitsAPIError(
                    f"StockTwits returned status {response.status_code} for '{ticker}': "
                    f"{response.text[:200]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise StockTwitsAPIError(f"StockTwits returned invalid JSON for '{ticker}'") from exc

            messages = (payload.get("messages") or {}).get("messages") or []
            if not isinstance(messages, list):
                logger.warning("StockTwits returned unexpected messages shape for '%s'; skipping", ticker)
                continue

            for item in messages:
                msg_id = item.get("id")
                body = item.get("body")
                created_raw = item.get("created_at")
                if msg_id is None or not body or not created_raw:
                    continue

                try:
                    created_at = datetime.strptime(
                        created_raw, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc).replace(tzinfo=None)
                except ValueError:
                    logger.warning(
                        "Discarding StockTwits message with unparseable created_at: %s", created_raw
                    )
                    continue

                if since is not None and created_at < since:
                    continue

                user = item.get("user") or {}
                entities = item.get("entities") or {}
                sentiment_obj = (entities.get("sentiment") or {}).get("basic")
                sentiment = sentiment_obj if sentiment_obj in ("Bullish", "Bearish") else None

                username = user.get("username") or ""
                name = user.get("name") or None
                likes = (item.get("likes") or {}).get("total") or 0
                reshares = (item.get("reshares") or {}).get("resharers") or 0

                all_messages.append(
                    StockTwitsMessage(
                        message_id=str(msg_id),
                        symbol=ticker,
                        text=body,
                        created_at=created_at,
                        author_username=username,
                        author_name=name,
                        sentiment=sentiment,
                        url=f"https://stocktwits.com/message/{msg_id}",
                        likes=int(likes),
                        reshares=int(reshares),
                    )
                )

        logger.info(
            "Fetched %d StockTwits messages across %d symbols", len(all_messages), len(tickers)
        )
        return all_messages
