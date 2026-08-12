"""Finnhub source adapter (Sprint 4, Sprint 7 extension): FinnhubClient -> NormalizedEvent.

Originally (Sprint 4): company-news articles via Finnhub's ticker-scoped
company-news endpoint.

Extended in Sprint 7: additionally emits per-ticker aggregated social
sentiment events (Reddit + X mention counts, weighted sentiment score
-1..1) via Finnhub's `/stock/social-sentiment` endpoint. Articles use
`source_type="news"` for the normal credibility tier; social-sentiment
aggregates use `source_type="news_social"` so they get a social-tier
credibility score without needing a separate adapter.

Why combine them in one adapter:
  * Both endpoints use the same API key + rate-limit pool (60 req/min free).
  * They share the ticker universe so pairing them avoids a second set of
    builder functions / system_config flags in the worker.
  * If the social endpoint ever returns 403 (paid-only on some plans), we
    log-and-skip without losing the company-news stream.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from app.exceptions import NewsAPIError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.news.finnhub_client import FinnhubClient, FinnhubSocialSentiment


def _direction(s: FinnhubSocialSentiment) -> str:
    score = s.overall_score
    if score >= 0.25:
        return f"Bullish ({score*100:+.0f})"
    if score <= -0.25:
        return f"Bearish ({score*100:+.0f})"
    return f"Neutral ({score*100:+.0f})"


class NewsAdapter(SourceAdapter):
    source_name = "Finnhub"
    source_type = "news"

    def __init__(
        self,
        client: FinnhubClient,
        tickers: list[str],
        include_social_sentiment: bool = True,
    ):
        self._client = client
        self._tickers = tickers
        self._include_social = include_social_sentiment

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        events: list[NormalizedEvent] = []

        try:
            articles = await self._client.fetch_company_news(self._tickers, since=since)
        except NewsAPIError as exc:
            raise IngestionError(str(exc)) from exc

        for article in articles:
            events.append(
                NormalizedEvent(
                    source_name=article.source_name,
                    source_type=self.source_type,
                    source_event_id=article.article_id,
                    published_at=article.published_at,
                    title=article.headline,
                    content=article.summary or article.headline,
                    url=article.url,
                    author=None,
                    # Ticker doubles as a stable "account" id here so downstream
                    # SourceAccount bookkeeping (app.workers.news_ingestion.
                    # get_or_create_source_account) has something to key on,
                    # mirroring how CompanyIRAdapter uses the feed URL.
                    source_account_external_id=article.ticker,
                )
            )

        if not self._include_social:
            return events

        try:
            social_rows = await self._client.fetch_social_sentiment(self._tickers, since=since)
        except NewsAPIError as exc:
            # Social-sentiment errors are non-fatal for the overall adapter
            # so a 429 or plan-gated 403 on the social endpoint doesn't
            # kill the company-news stream that already got ingested.
            logger = __import__("logging").getLogger(__name__)
            logger.warning("Finnhub social-sentiment fetch failed (non-fatal): %s", exc)
            social_rows = []

        for s in social_rows:
            direction = _direction(s)
            day_key = s.published_at.strftime("%Y%m%d")
            title = (
                f"Social Buzz [{direction}]: ${s.ticker} "
                f"{s.total_mentions:,} mentions (Reddit {s.reddit_mentions} + X {s.twitter_mentions})"
            )
            content = (
                f"Finnhub aggregated social-sentiment signal for ${s.ticker} "
                f"(period = last {s.period}):\n"
                f"- Total mentions: {s.total_mentions:,}\n"
                f"- Reddit: {s.reddit_mentions:,} mentions (pos {s.reddit_positive_mentions} / "
                f"neg {s.reddit_negative_mentions}; score {s.reddit_score*100:+.0f})\n"
                f"- X/Twitter: {s.twitter_mentions:,} mentions (pos {s.twitter_positive_mentions} / "
                f"neg {s.twitter_negative_mentions}; score {s.twitter_score*100:+.0f})\n"
                f"- Overall weighted score: {s.overall_score*100:+.0f}"
            )
            events.append(
                NormalizedEvent(
                    source_name="Finnhub Social",
                    source_type="news_social",
                    source_event_id=f"FH-SOC-{s.ticker}-{day_key}",
                    published_at=s.published_at,
                    title=title[:250],
                    content=content,
                    url=f"https://finnhub.io/quote/{s.ticker}",
                    author="Finnhub Aggregate",
                    source_account_external_id=f"social:{s.ticker}",
                    language="en",
                    raw_metadata={
                        "signal_type": "finnhub_social_sentiment",
                        "ticker": s.ticker,
                        "period": s.period,
                        "total_mentions": s.total_mentions,
                        "reddit_mentions": s.reddit_mentions,
                        "reddit_score": s.reddit_score,
                        "reddit_pos": s.reddit_positive_mentions,
                        "reddit_neg": s.reddit_negative_mentions,
                        "twitter_mentions": s.twitter_mentions,
                        "twitter_score": s.twitter_score,
                        "twitter_pos": s.twitter_positive_mentions,
                        "twitter_neg": s.twitter_negative_mentions,
                        "overall_score": s.overall_score,
                        "direction": direction,
                    },
                )
            )

        return events
