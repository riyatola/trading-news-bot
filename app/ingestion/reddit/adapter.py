"""Reddit source adapter (Sprint 7): RedditClient -> NormalizedEvent.

Scans the newest posts from r/wallstreetbets, r/stocks, r/investing and
keeps only those that mention at least one tracked ticker symbol (via
the standard `$TICKER` pattern and a bare-TICKER allowlist of the 52
tracked assets -- kept conservative to avoid false positives on short
English words like "A" or "ALL"). Tickers extracted per post are stored
in `raw_metadata["mentioned_tickers"]` so downstream entity extraction
(Sprint 5's LLM step) gets a strong hint it can cross-check.

source_type = "reddit"; source_name = "Reddit" + subreddit in
source_account_external_id. Credibility tier defaults to 3 (social) per
_DEFAULT_TIER_BY_SOURCE_TYPE in the news_ingestion worker.

Reddit has no built-in ticker tagging, unlike StockTwits, so the
adapter is the right place to run this extraction -- the RedditClient
stays pure (raw RedditPost only) and is therefore easy to unit test.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Sequence

from app.exceptions import RedditAPIError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.reddit.reddit_client import RedditClient

_DOLLAR_TICKER_RE = re.compile(r"\$([A-Z]{1,6})\b")
# Tracked-ticker-only pattern to match $NVDA, NVDA, (NVDA), etc. for the
# known universe. We deliberately avoid a naive "any 2-5 letter word"
# regex because that catches e.g. "CEO", "SEC", "PDF" etc. at high rates.
_WORD_BOUNDARY_RE = re.compile(r"\b([A-Z]{2,6})\b")

_DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


class RedditAdapter(SourceAdapter):
    source_name = "Reddit"
    source_type = "reddit"

    def __init__(
        self,
        client: RedditClient,
        tracked_tickers: list[str],
        subreddits: tuple[str, ...] = _DEFAULT_SUBREDDITS,
        limit_per_sub: int = 50,
    ):
        self._client = client
        self._tickers_upper = {t.upper() for t in tracked_tickers}
        self._subreddits = subreddits
        self._limit_per_sub = limit_per_sub

    def _extract_tickers(self, text: str) -> list[str]:
        if not text:
            return []
        found: set[str] = set()
        for match in _DOLLAR_TICKER_RE.findall(text):
            ticker = match.upper()
            if ticker in self._tickers_upper:
                found.add(ticker)
        for match in _WORD_BOUNDARY_RE.findall(text):
            ticker = match.upper()
            if ticker in self._tickers_upper:
                found.add(ticker)
        return sorted(found)

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        try:
            posts = await self._client.fetch_sub_new(
                subreddits=self._subreddits, limit_per_sub=self._limit_per_sub, since=since
            )
        except RedditAPIError as exc:
            raise IngestionError(str(exc)) from exc

        events: list[NormalizedEvent] = []
        for post in posts:
            combined = f"{post.title}\n{post.selftext}"
            mentioned_tickers = self._extract_tickers(combined)
            if not mentioned_tickers:
                continue

            primary_ticker = mentioned_tickers[0]
            content = post.selftext or post.title
            events.append(
                NormalizedEvent(
                    source_name=self.source_name,
                    source_type=self.source_type,
                    source_event_id=f"RD-{post.post_id}",
                    published_at=post.created_at,
                    title=f"r/{post.subreddit}: {post.title[:120]}",
                    content=content,
                    url=post.permalink or post.url or None,
                    author=f"u/{post.author_username}" if post.author_username else None,
                    source_account_external_id=post.subreddit,
                    language="en",
                    raw_metadata={
                        "mentioned_tickers": mentioned_tickers,
                        "subreddit": post.subreddit,
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "primary_ticker": primary_ticker,
                    },
                )
            )

        return events
