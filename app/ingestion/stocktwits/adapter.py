"""StockTwits source adapter (Sprint 7): StockTwitsClient -> NormalizedEvent.

StockTwits is the closest analog to X for finance-only social, and its
ticker-scoped streams (same pattern as our Finnhub client) replace the
original X adapter's retail-sentiment coverage entirely -- no paid tier
required for basic streams, and the `Bullish`/`Bearish` tags that come
for free on many posts can reduce downstream LLM work.

source_type = "stocktwits", source_name = "StockTwits" by default (each
message's specific ticker is preserved in `source_account_external_id`
and `raw_metadata["sentiment"]` contains the direct Bullish/Bearish tag
if available).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from app.exceptions import StockTwitsAPIError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.stocktwits.stocktwits_client import StockTwitsClient


class StockTwitsAdapter(SourceAdapter):
    source_name = "StockTwits"
    source_type = "stocktwits"

    def __init__(self, client: StockTwitsClient, tickers: list[str]):
        self._client = client
        self._tickers = tickers

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        try:
            messages = await self._client.fetch_symbol_stream(self._tickers, since=since)
        except StockTwitsAPIError as exc:
            raise IngestionError(str(exc)) from exc

        return [
            NormalizedEvent(
                source_name=self.source_name,
                source_type=self.source_type,
                source_event_id=f"ST-{m.message_id}",
                published_at=m.created_at,
                title=self._make_title(m),
                content=m.text,
                url=m.url,
                author=m.author_name or m.author_username or None,
                source_account_external_id=m.symbol,
                language="en",
                raw_metadata={
                    "sentiment": m.sentiment,
                    "symbol": m.symbol,
                    "likes": m.likes,
                    "reshares": m.reshares,
                    "author_username": m.author_username,
                },
            )
            for m in messages
        ]

    @staticmethod
    def _make_title(m) -> str:
        sentiment_tag = f"[{m.sentiment}] " if m.sentiment else ""
        author = f"@{m.author_username}" if m.author_username else "StockTwits"
        prefix = f"{sentiment_tag}{author} on ${m.symbol}: "
        text = m.text[:120].replace("\n", " ")
        return f"{prefix}{text}"
