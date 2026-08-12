"""ApeWisdom source adapter (Sprint 7): ApeWisdomClient -> NormalizedEvent.

Turns ApeWisdom's WSB mention-rank data into NormalizedEvents the rest of
the pipeline can deduplicate, classify, and score alongside news/filings
posts. Each ticker on ApeWisdom becomes one event per ingestion poll so
rank spikes (e.g. a ticker jumping from #150 to #5 in 24 hours) are
visible to the downstream alert engine as raw content.

Rationale for creating one event per ranked ticker (rather than one
aggregate event per poll):
  * Dedup works on (source_id, source_event_id) — using a compound
    `{ticker}_{YYYYMMDD}` ID means we get one dedup-protected row per
    tracked ticker per day, which is enough volume for the LLM/alerting
    side while still surfacing 24h rank changes.
  * The LLM prefilter + analyzer already handles "structured data
    masquerading as a news post" (c.f. Quiver's congress_trade events)
    and will classify a rank-spike event correctly if it's surfaced in
    the title/content, which we craft for readability below.

source_type = "apewisdom", source_name = "ApeWisdom WSB".
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from app.exceptions import ApeWisdomAPIError
from app.ingestion.apewisdom.apewisdom_client import ApeWisdomTicker
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.apewisdom.apewisdom_client import ApeWisdomClient

# Sentiment proportions above these thresholds get a direction tag.
_BULL_THRESHOLD = 0.55
_BEAR_THRESHOLD = 0.55
# A ticker needs at least this many mentions to be emitted as an event.
# 3 mentions on WSB is enough signal to register without noise.
_MIN_MENTIONS = 3


def _direction(t: ApeWisdomTicker) -> str:
    if t.sentiment_bull >= _BULL_THRESHOLD:
        return "Bullish"
    if t.sentiment_bear >= _BEAR_THRESHOLD:
        return "Bearish"
    if t.sentiment_spy >= 0.35:
        return "Macro/SPY"
    return "Mixed"


def _rank_delta(t: ApeWisdomTicker) -> str:
    if t.rank_24h_ago is None or t.rank_24h_ago <= 0:
        return "NEW"
    delta = t.rank_24h_ago - t.rank  # positive => moved up the ranking
    if delta > 0:
        return f"+{delta} (up to #{t.rank})"
    if delta < 0:
        return f"{delta} (down to #{t.rank})"
    return f"flat (held #{t.rank})"


class ApeWisdomAdapter(SourceAdapter):
    source_name = "ApeWisdom WSB"
    source_type = "apewisdom"

    def __init__(self, client: ApeWisdomClient, tracked_tickers: list[str]):
        self._client = client
        self._tickers = tracked_tickers

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        try:
            rows = await self._client.fetch_mentions(self._tickers)
        except ApeWisdomAPIError as exc:
            raise IngestionError(str(exc)) from exc

        # `since` is used by the worker to avoid re-emitting rows within
        # the lookback window. ApeWisdom rows are daily aggregates, so we
        # key source_event_id by ticker + UTC day, which dedups multiple
        # polls in the same day naturally. We still honour `since` at
        # the margin (drop rows whose fetch time predates `since` by more
        # than 12h) to be consistent with other adapters, though in
        # practice the source_event_id dedup below is what prevents
        # duplicates on the DB side.
        since_cutoff = (since - timedelta(hours=12)) if since is not None else None

        events: list[NormalizedEvent] = []
        for t in rows:
            if t.mentions < _MIN_MENTIONS:
                continue
            if since_cutoff is not None and t.fetched_at < since_cutoff:
                continue

            direction = _direction(t)
            delta = _rank_delta(t)
            title = (
                f"WSB Buzz [{direction}]: ${t.ticker} #{t.rank} "
                f"({t.mentions} mentions, 24h {delta})"
            )
            content_parts = [
                f"r/wallstreetbets retail-attention signal for ${t.ticker}:",
                f"- Current rank: #{t.rank} (24h change: {delta})",
                f"- Mentions in last 24h: {t.mentions}",
                f"- Upvotes on WSB: {t.upvotes:,}",
                f"- Sentiment: Bull {t.sentiment_bull*100:.0f}% / "
                f"Bear {t.sentiment_bear*100:.0f}% / SPY {t.sentiment_spy*100:.0f}%",
            ]
            if t.mention_24h_ago:
                pct = ((t.mentions - t.mention_24h_ago) / t.mention_24h_ago * 100) if t.mention_24h_ago else 0
                content_parts.append(
                    f"- Mentions vs 24h ago: {t.mention_24h_ago} -> {t.mentions} ({pct:+.0f}%)"
                )

            day_key = t.fetched_at.strftime("%Y%m%d")
            events.append(
                NormalizedEvent(
                    source_name=self.source_name,
                    source_type=self.source_type,
                    source_event_id=f"AW-{t.ticker}-{day_key}",
                    published_at=t.fetched_at,
                    title=title[:250],
                    content="\n".join(content_parts),
                    url="https://apewisdom.io/",
                    author="ApeWisdom / r/wallstreetbets",
                    source_account_external_id=f"wsb:{t.ticker}",
                    language="en",
                    raw_metadata={
                        "ticker": t.ticker,
                        "rank": t.rank,
                        "rank_24h_ago": t.rank_24h_ago,
                        "mentions": t.mentions,
                        "mentions_24h_ago": t.mention_24h_ago,
                        "upvotes": t.upvotes,
                        "sentiment_bull": t.sentiment_bull,
                        "sentiment_bear": t.sentiment_bear,
                        "sentiment_spy": t.sentiment_spy,
                        "direction": direction,
                    },
                )
            )

        return events
