"""Finnhub company-news client (Sprint 4, replaces NewsAPI).

Uses Finnhub's `/api/v1/company-news` endpoint, which is *ticker-scoped*
rather than free-text-company-name-scoped like NewsAPI's `/v2/everything`.
This is a natural fit for this project: we already maintain a fixed
52-ticker universe (`app.db.models.Asset`), so there's no need for the
boolean-OR company-name query NewsAPI required.

Mirrors the error-handling shape of `app.market.mexc.MEXCClient` /
`app.ingestion.sec.edgar_client.SECEDGARClient`: network/shape failures
raise `NewsAPIError` (kept as the shared exception name so
`app.workers.news_ingestion` / `app.ingestion.news.adapter` don't need to
change their exception handling) so the adapter/worker can apply
consistent retry/dead-letter handling.

One request per ticker (Finnhub's company-news endpoint doesn't support a
batched/OR query the way NewsAPI's did) -- comparable in shape to
`app.ingestion.sec.edgar_client.SECEDGARClient.search_filings`. Finnhub's
free tier allows 60 API calls/minute, which comfortably covers a 52-ticker
universe polled every few minutes (see
`app.workers.scheduler.NEWS_INGESTION_INTERVAL_MINUTES`).

Note: Finnhub's `from`/`to` params are calendar dates (not timestamps), so
`since` is truncated to a date. Re-fetching the same day's articles on
every poll is expected and harmless -- `persist_normalized_event`
deduplicates on (source_id, source_event_id) via the raw_events unique
constraint.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import httpx

from app.exceptions import NewsAPIError

logger = logging.getLogger(__name__)

FINNHUB_COMPANY_NEWS_URL = "https://finnhub.io/api/v1/company-news"
FINNHUB_STOCK_SOCIAL_SENTIMENT_URL = "https://finnhub.io/api/v1/stock/social-sentiment"
DEFAULT_TIMEOUT_SECONDS = 10.0
# How far back to look if no watermark is available (cold start). Finnhub
# free tier historical coverage is generous, but there's no reason to
# pull more than a day or two on a fresh install -- subsequent polls use
# the worker's last-successful-poll watermark instead (see
# app.workers.news_ingestion.NewsIngestionWorker).
DEFAULT_LOOKBACK_DAYS = 1
# Social sentiment: Finnhub returns per-hour buckets for the last 24h by
# default. On a cold start we ask for 3 days (72h) to match the worker's
# normal lookback window.
SOCIAL_DEFAULT_LOOKBACK_DAYS = 1
# Minimum Reddit + X mentions for a ticker to bother emitting an event.
# 0-2 total mentions is noise; 3+ is worth passing to the LLM gate.
SOCIAL_MIN_TOTAL_MENTIONS = 3


@dataclass(frozen=True)
class FinnhubArticle:
    ticker: str
    source_name: str
    headline: str
    summary: Optional[str]
    url: str
    published_at: datetime
    article_id: str  # Finnhub's numeric "id" field, stringified


@dataclass(frozen=True)
class FinnhubSocialSentiment:
    """Aggregated 24h Reddit + X social sentiment per ticker from Finnhub."""

    ticker: str
    period: str          # e.g. "24h" or a bucket label
    published_at: datetime
    reddit_mentions: int
    reddit_score: float   # -1..1 per Finnhub docs (positive = bullish)
    reddit_positive_mentions: int
    reddit_negative_mentions: int
    twitter_mentions: int
    twitter_score: float  # -1..1
    twitter_positive_mentions: int
    twitter_negative_mentions: int

    @property
    def total_mentions(self) -> int:
        return self.reddit_mentions + self.twitter_mentions

    @property
    def overall_score(self) -> float:
        """Weighted sentiment score (-1..1), weighted by mention volume."""
        w_reddit = self.reddit_mentions
        w_twitter = self.twitter_mentions
        total = w_reddit + w_twitter
        if total <= 0:
            return 0.0
        return (self.reddit_score * w_reddit + self.twitter_score * w_twitter) / total


class FinnhubClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = FINNHUB_COMPANY_NEWS_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._client = client  # injectable for testing

    async def fetch_company_news(
        self, tickers: list[str], since: Optional[datetime] = None
    ) -> list[FinnhubArticle]:
        """Fetch recent company-news articles for each of `tickers`.

        Raises:
            NewsAPIError: on missing API key, network failure, rate
                limiting, non-200 response, or an unexpected response
                shape.
        """
        if not self._api_key:
            raise NewsAPIError("Finnhub request skipped: no API key configured")
        if not tickers:
            return []

        from_date: date = (
            since.date() if since is not None
            else (datetime.utcnow() - _lookback()).date()
        )
        to_date: date = datetime.utcnow().date()

        all_articles: list[FinnhubArticle] = []

        for ticker in tickers:
            params = {
                "symbol": ticker,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "token": self._api_key,
            }

            try:
                if self._client is not None:
                    response = await self._client.get(
                        self._base_url, params=params, timeout=self._timeout
                    )
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            self._base_url, params=params, timeout=self._timeout
                        )
            except httpx.HTTPError as exc:
                raise NewsAPIError(f"Finnhub request failed for '{ticker}': {exc}") from exc

            if response.status_code == 429:
                raise NewsAPIError("Finnhub rate limit exceeded (429)")
            if response.status_code != 200:
                raise NewsAPIError(
                    f"Finnhub returned status {response.status_code} for '{ticker}': "
                    f"{response.text[:200]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise NewsAPIError(f"Finnhub returned invalid JSON for '{ticker}'") from exc

            if not isinstance(payload, list):
                # Finnhub returns {} for an invalid/unrecognized symbol
                # instead of a 4xx -- treat as "no articles", not an error,
                # so one bad/delisted ticker doesn't dead-letter the whole
                # adapter run.
                logger.warning("Finnhub returned unexpected shape for '%s'; skipping", ticker)
                continue

            for item in payload:
                item_id = item.get("id")
                url = item.get("url")
                headline = item.get("headline")
                ts = item.get("datetime")
                if item_id is None or not url or not headline or not ts:
                    continue
                try:
                    published_at = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
                except (TypeError, ValueError, OSError):
                    logger.warning("Discarding Finnhub article with unparseable datetime: %s", ts)
                    continue

                all_articles.append(
                    FinnhubArticle(
                        ticker=ticker,
                        source_name=item.get("source") or "Finnhub",
                        headline=headline,
                        summary=item.get("summary") or None,
                        url=url,
                        published_at=published_at,
                        article_id=str(item_id),
                    )
                )

        logger.info(
            "Fetched %d Finnhub articles across %d tickers", len(all_articles), len(tickers)
        )
        return all_articles

    # --- social sentiment endpoint ------------------------------------

    async def fetch_social_sentiment(
        self, tickers: list[str], since: Optional[datetime] = None
    ) -> list[FinnhubSocialSentiment]:
        """Fetch aggregated Reddit + X social sentiment per ticker.

        Finnhub's `/stock/social-sentiment` endpoint returns per-hour
        buckets for the last ~7 days, each with mention counts + a
        -1..1 sentiment score for Reddit and Twitter separately. We
        aggregate across all buckets within the lookback window to
        produce one `FinnhubSocialSentiment` row per ticker so the
        adapter emits one normalised event per ticker per poll.

        Rate limit note: this is 1 request per ticker; together with
        `fetch_company_news` we do 2x 52-ticker requests per poll =
        104 requests, well within Finnhub's free 60 req/min (news +
        social are the same pool). If budget is ever tight, social can
        be run every-other poll cycle via the feature flag.
        """
        if not self._api_key:
            raise NewsAPIError("Finnhub social-sentiment skipped: no API key configured")
        if not tickers:
            return []

        lookback_days = SOCIAL_DEFAULT_LOOKBACK_DAYS
        if since is not None:
            delta = datetime.utcnow() - since
            lookback_days = max(1, min(7, int(delta.total_seconds() // 86400) + 1))

        out: list[FinnhubSocialSentiment] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for ticker in tickers:
            params = {
                "symbol": ticker,
                "from": (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d"),
                "to": now.strftime("%Y-%m-%d"),
                "token": self._api_key,
            }
            try:
                if self._client is not None:
                    resp = await self._client.get(
                        FINNHUB_STOCK_SOCIAL_SENTIMENT_URL,
                        params=params, timeout=self._timeout,
                    )
                else:
                    async with httpx.AsyncClient() as http:
                        resp = await http.get(
                            FINNHUB_STOCK_SOCIAL_SENTIMENT_URL,
                            params=params, timeout=self._timeout,
                        )
            except httpx.HTTPError as exc:
                raise NewsAPIError(
                    f"Finnhub social-sentiment failed for '{ticker}': {exc}"
                ) from exc

            if resp.status_code == 429:
                raise NewsAPIError("Finnhub social-sentiment rate limit exceeded (429)")
            if resp.status_code == 403:
                # Some Finnhub social endpoints are paid-only; log and
                # skip rather than dead-letter so the news half of the
                # adapter still runs.
                logger.warning(
                    "Finnhub social-sentiment returned 403 for '%s' (plan restriction?); skipping endpoint",
                    ticker,
                )
                continue
            if resp.status_code != 200:
                logger.warning(
                    "Finnhub social-sentiment status %d for '%s': %s; skipping",
                    resp.status_code, ticker, resp.text[:150],
                )
                continue

            try:
                payload = resp.json()
            except ValueError:
                logger.warning("Finnhub social-sentiment returned bad JSON for '%s'", ticker)
                continue

            reddit = payload.get("reddit") if isinstance(payload, dict) else None
            twitter = payload.get("twitter") if isinstance(payload, dict) else None
            reddit_rows = reddit if isinstance(reddit, list) else []
            twitter_rows = twitter if isinstance(twitter, list) else []

            r_mentions = r_pos = r_neg = 0
            r_score_sum = 0.0
            r_score_w = 0
            for row in reddit_rows:
                m = int(row.get("mention") or 0)
                if m <= 0:
                    continue
                s = float(row.get("score") or 0)
                r_mentions += m
                r_pos += int(row.get("positiveMention") or 0)
                r_neg += int(row.get("negativeMention") or 0)
                r_score_sum += s * m
                r_score_w += m

            t_mentions = t_pos = t_neg = 0
            t_score_sum = 0.0
            t_score_w = 0
            for row in twitter_rows:
                m = int(row.get("mention") or 0)
                if m <= 0:
                    continue
                s = float(row.get("score") or 0)
                t_mentions += m
                t_pos += int(row.get("positiveMention") or 0)
                t_neg += int(row.get("negativeMention") or 0)
                t_score_sum += s * m
                t_score_w += m

            total = r_mentions + t_mentions
            if total < SOCIAL_MIN_TOTAL_MENTIONS:
                continue

            out.append(
                FinnhubSocialSentiment(
                    ticker=ticker,
                    period=f"{lookback_days}d",
                    published_at=now,
                    reddit_mentions=r_mentions,
                    reddit_score=(r_score_sum / r_score_w) if r_score_w else 0.0,
                    reddit_positive_mentions=r_pos,
                    reddit_negative_mentions=r_neg,
                    twitter_mentions=t_mentions,
                    twitter_score=(t_score_sum / t_score_w) if t_score_w else 0.0,
                    twitter_positive_mentions=t_pos,
                    twitter_negative_mentions=t_neg,
                )
            )

        logger.info(
            "Fetched Finnhub social sentiment for %d/%d tickers (≥%d mentions)",
            len(out), len(tickers), SOCIAL_MIN_TOTAL_MENTIONS,
        )
        return out


def _lookback():
    from datetime import timedelta
    return timedelta(days=DEFAULT_LOOKBACK_DAYS)


# Used inside FinnhubClient.fetch_social_sentiment default arg; moved to
# bottom to avoid circular/forward-reference import order issues.
from datetime import timedelta  # noqa: E402
