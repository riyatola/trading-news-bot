"""Quiver Quantitative source adapter (Sprint 7): QuiverQuantClient -> NormalizedEvent.

Turns 4 signal types (congressional trades, corporate insider trades,
WSB aggregate sentiment, Google Trends) into the same NormalizedEvent
shape the rest of the ingestion pipeline uses. Each signal type is
labelled in raw_metadata["signal_type"] so downstream classification
can handle them separately, and also gets a source-specific title so
operators reading raw_events / alerts can immediately tell the signal
apart from ordinary news posts.

- source_type = "quiver"
- credibility tier default (in _DEFAULT_TIER_BY_SOURCE_TYPE on the
  news_ingestion worker) = 2 (0.7) for congress/insider filings (these
  are regulatory records, not rumour), 3 for WSB/Google aggregates.
  Per-signal-type tier is overridable in the Source table seed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from app.exceptions import QuiverQuantAPIError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.quiverquant.quiver_client import QuiverQuantClient


class QuiverQuantAdapter(SourceAdapter):
    source_name = "Quiver Quantitative"
    source_type = "quiver"

    def __init__(self, client: QuiverQuantClient, tickers: list[str]):
        self._client = client
        self._tickers = tickers

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        try:
            batch = await self._client.fetch_batch(self._tickers, since=since)
        except QuiverQuantAPIError as exc:
            raise IngestionError(str(exc)) from exc

        events: list[NormalizedEvent] = []

        for t in batch.congress_trades:
            direction = "BUY" if t.transaction_type.lower().startswith("pur") else "SELL"
            title = (
                f"Congress Trade [{direction}]: Rep {t.representative} "
                f"{t.transaction_type} ${t.ticker} ({t.amount_range})"
            )
            content = (
                f"US Congress trade disclosure for ${t.ticker}:\n"
                f"- Representative: {t.representative}\n"
                f"- Transaction: {t.transaction_type}\n"
                f"- Amount range: {t.amount_range}\n"
                f"- Report date: {t.report_date.date() if t.report_date else 'n/a'}\n"
                f"- Transaction date: {t.transaction_date.date() if t.transaction_date else 'n/a'}\n"
                + (f"- Notes: {t.description}\n" if t.description else "")
            )
            events.append(
                NormalizedEvent(
                    source_name=self.source_name,
                    source_type=self.source_type,
                    source_event_id=f"QV-CT-{t.ticker}-{t.report_date.strftime('%Y%m%d')}-{t.representative[:10]}",
                    published_at=t.report_date or datetime.utcnow(),
                    title=title[:250],
                    content=content,
                    url=None,
                    author=t.representative or None,
                    source_account_external_id=f"congress:{t.ticker}",
                    language="en",
                    raw_metadata={
                        "signal_type": "congress_trade",
                        "ticker": t.ticker,
                        "transaction_type": direction,
                        "amount_range": t.amount_range,
                        "representative": t.representative,
                        "description": t.description,
                    },
                )
            )

        for t in batch.insider_trades:
            direction = "BUY" if ("purchase" in t.transaction_type.lower() or "buy" in t.transaction_type.lower()) else "SELL"
            dollar_str = (
                f"${t.d_value:,.0f}" if t.d_value is not None else
                (f"{t.shares:,} shares @ ${t.last_price:,.2f}" if t.last_price is not None else f"{t.shares:,} shares")
            )
            title = (
                f"Insider Trade [{direction}]: {t.insider_name} ({t.insider_title}) "
                f"{t.transaction_type} ${t.ticker} -- {dollar_str}"
            )
            content = (
                f"Form 4 insider trade for ${t.ticker}:\n"
                f"- Insider: {t.insider_name} ({t.insider_title})\n"
                f"- Transaction: {t.transaction_type}\n"
                f"- Shares: {t.shares:,}\n"
                + (f"- Last price: ${t.last_price:,.2f}\n" if t.last_price is not None else "")
                + (f"- Value change: ${t.d_value:,.0f}\n" if t.d_value is not None else "")
                + f"- Report date: {t.report_date.date() if t.report_date else 'n/a'}\n"
                + f"- Transaction date: {t.transaction_date.date() if t.transaction_date else 'n/a'}"
            )
            events.append(
                NormalizedEvent(
                    source_name=self.source_name,
                    source_type=self.source_type,
                    source_event_id=f"QV-IT-{t.ticker}-{t.report_date.strftime('%Y%m%d')}-{t.insider_name[:10]}",
                    published_at=t.report_date or datetime.utcnow(),
                    title=title[:250],
                    content=content,
                    url=None,
                    author=t.insider_name or None,
                    source_account_external_id=f"insider:{t.ticker}",
                    language="en",
                    raw_metadata={
                        "signal_type": "insider_trade",
                        "ticker": t.ticker,
                        "transaction_type": direction,
                        "insider_name": t.insider_name,
                        "insider_title": t.insider_title,
                        "shares": t.shares,
                        "last_price": t.last_price,
                        "d_value": t.d_value,
                    },
                )
            )

        for s in batch.wsb_sentiment:
            direction = "Bullish" if s.sentiment > 0.1 else ("Bearish" if s.sentiment < -0.1 else "Neutral")
            title = (
                f"WSB Aggregate [{direction}]: ${s.ticker} mentioned {s.mentions:,}x "
                f"(sentiment {s.sentiment*100:+.0f})"
            )
            content = (
                f"Quiver WSB sentiment aggregate for ${s.ticker}:\n"
                f"- Date: {s.date.date() if s.date else 'n/a'}\n"
                f"- Mentions on WSB: {s.mentions:,}\n"
                f"- Aggregate sentiment: {s.sentiment*100:+.0f} ({direction})\n"
                + (f"- WSB rank: #{s.rank}\n" if s.rank is not None else "")
            )
            events.append(
                NormalizedEvent(
                    source_name=self.source_name,
                    source_type=self.source_type,
                    source_event_id=f"QV-WSB-{s.ticker}-{s.date.strftime('%Y%m%d')}",
                    published_at=s.date or datetime.utcnow(),
                    title=title[:250],
                    content=content,
                    url=None,
                    author="Quiver/WSB",
                    source_account_external_id=f"wsb:{s.ticker}",
                    language="en",
                    raw_metadata={
                        "signal_type": "wsb_sentiment",
                        "ticker": s.ticker,
                        "mentions": s.mentions,
                        "sentiment": s.sentiment,
                        "rank": s.rank,
                        "direction": direction,
                    },
                )
            )

        for g in batch.google_trends:
            title = (
                f"Google Trends [Spike]: ${g.ticker} search interest = {g.search_interest}/100"
            )
            content = (
                f"Google Trends search-volume data for ${g.ticker}:\n"
                f"- Date: {g.date.date() if g.date else 'n/a'}\n"
                f"- Search interest: {g.search_interest}/100 (Google Trends relative 0..100 scale)\n"
                f"- Interpretation: 100 = peak attention for the trailing 5y window, 50 = half that peak, etc."
            )
            events.append(
                NormalizedEvent(
                    source_name=self.source_name,
                    source_type=self.source_type,
                    source_event_id=f"QV-GT-{g.ticker}-{g.date.strftime('%Y%m%d')}",
                    published_at=g.date or datetime.utcnow(),
                    title=title[:250],
                    content=content,
                    url=None,
                    author="Google Trends (via Quiver)",
                    source_account_external_id=f"google_trends:{g.ticker}",
                    language="en",
                    raw_metadata={
                        "signal_type": "google_trends",
                        "ticker": g.ticker,
                        "search_interest": g.search_interest,
                    },
                )
            )

        return events
