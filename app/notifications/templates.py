"""Telegram alert message templates (Sprint 6).

Each `render_*` function turns already-loaded ORM rows into the Markdown
text for one Telegram message. Kept as pure string-formatting (no DB or
network access) so they're easy to unit test in isolation, mirroring how
`app.intelligence.prompts.build_user_prompt` separates "build the text"
from "do the I/O" in `app.workers.event_processing`.

Field sets per channel follow the README's alert-template spec:
- LONG/SHORT: asset, score, catalyst, fundamental impact, price reaction,
  volume, cross-asset effects, macro regime, time horizon, confidence,
  sources
- MACRO: event, market impact, affected assets, regime, expected horizon
- MARKET: price/volume/OI anomalies
- DAILY: macro regime, major developments, watchlists, upcoming risks
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from app.db.models import (
    Asset, Event, EventEntity, MacroSnapshot, MarketSnapshot, Opportunity, RawEvent,
)


def _confidence_bar(value: Optional[int]) -> str:
    if value is None:
        return "n/a"
    filled = max(0, min(10, round((value / 100) * 10)))
    return f"{'█' * filled}{'░' * (10 - filled)} {value}%"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _cross_asset_lines(entities: Sequence[EventEntity], assets_by_id: dict) -> str:
    lines = []
    for e in entities:
        if e.relationship == "direct":
            continue
        asset = assets_by_id.get(e.asset_id)
        if not asset:
            continue
        lines.append(f"  • {asset.ticker} ({e.relationship}, {e.direction}): {e.impact}")
    return "\n".join(lines) if lines else "  • none identified"


def _price_line(market_snapshot: Optional[MarketSnapshot]) -> str:
    if market_snapshot is None:
        return "n/a (event-only/unconfirmed -- no market data yet)"
    returns = (market_snapshot.indicators or {}).get("returns", {})
    return (
        f"${market_snapshot.price:.2f}  (1h {_fmt_pct(returns.get('1h'))}, "
        f"24h {_fmt_pct(returns.get('24h'))})"
    )


def _volume_line(market_snapshot: Optional[MarketSnapshot]) -> str:
    if market_snapshot is None:
        return "n/a"
    rel_vol = (market_snapshot.indicators or {}).get("relative_volume_24h")
    return f"{rel_vol}x relative" if rel_vol is not None else "n/a"


def _confirmation_flag(opportunity: Opportunity) -> str:
    return "" if opportunity.market_confirmation_available else "  ⚠️ event-only/unconfirmed"


def render_long_alert(
    opportunity: Opportunity,
    event: Event,
    raw_event: RawEvent,
    asset: Asset,
    entities: Sequence[EventEntity],
    assets_by_id: dict,
    market_snapshot: Optional[MarketSnapshot] = None,
) -> str:
    return (
        f"🟢 *LONG — {asset.ticker}* ({asset.company_name})\n"
        f"Score: *{opportunity.long_score}/100*{_confirmation_flag(opportunity)}\n\n"
        f"*Catalyst:* {event.catalyst}\n"
        f"*Fundamental impact:* {event.reasoning_summary}\n"
        f"*Price:* {_price_line(market_snapshot)}\n"
        f"*Volume:* {_volume_line(market_snapshot)}\n"
        f"*Cross-asset effects:*\n{_cross_asset_lines(entities, assets_by_id)}\n"
        f"*Macro regime relevance:* {event.macro_relevance}/100\n"
        f"*Time horizon:* {event.time_horizon}\n"
        f"*Confidence:* {_confidence_bar(event.confidence)}\n"
        f"*Source:* {raw_event.url or raw_event.title}\n"
    )


def render_short_alert(
    opportunity: Opportunity,
    event: Event,
    raw_event: RawEvent,
    asset: Asset,
    entities: Sequence[EventEntity],
    assets_by_id: dict,
    market_snapshot: Optional[MarketSnapshot] = None,
) -> str:
    return (
        f"🔴 *SHORT — {asset.ticker}* ({asset.company_name})\n"
        f"Score: *{opportunity.short_score}/100*{_confirmation_flag(opportunity)}\n\n"
        f"*Catalyst:* {event.catalyst}\n"
        f"*Fundamental impact:* {event.reasoning_summary}\n"
        f"*Price:* {_price_line(market_snapshot)}\n"
        f"*Volume:* {_volume_line(market_snapshot)}\n"
        f"*Cross-asset effects:*\n{_cross_asset_lines(entities, assets_by_id)}\n"
        f"*Macro regime relevance:* {event.macro_relevance}/100\n"
        f"*Time horizon:* {event.time_horizon}\n"
        f"*Confidence:* {_confidence_bar(event.confidence)}\n"
        f"*Source:* {raw_event.url or raw_event.title}\n"
    )


def render_macro_alert(
    opportunity: Opportunity,
    event: Event,
    raw_event: RawEvent,
    entities: Sequence[EventEntity],
    assets_by_id: dict,
) -> str:
    return (
        f"🌐 *MACRO*\n\n"
        f"*Event:* {event.catalyst}\n"
        f"*Market impact:* {event.reasoning_summary}\n"
        f"*Affected assets:*\n{_cross_asset_lines(entities, assets_by_id)}\n"
        f"*Macro relevance:* {event.macro_relevance}/100\n"
        f"*Expected horizon:* {event.time_horizon}\n"
        f"*Score:* {opportunity.macro_score}/100\n"
        f"*Source:* {raw_event.url or raw_event.title}\n"
    )


def render_market_alert(
    opportunity: Opportunity,
    asset: Asset,
    market_snapshot: Optional[MarketSnapshot],
    event: Optional[Event] = None,
) -> str:
    if market_snapshot is None:
        detail = "No market data available for this asset (event-only/unconfirmed)."
    else:
        returns = (market_snapshot.indicators or {}).get("returns", {})
        detail = (
            f"Price: ${market_snapshot.price:.2f}  ({_fmt_pct(returns.get('1h'))} 1h, "
            f"{_fmt_pct(returns.get('24h'))} 24h)\n"
            f"Relative volume (24h): {_volume_line(market_snapshot)}\n"
            f"Open interest: {market_snapshot.open_interest}\n"
            f"Funding rate: {market_snapshot.funding_rate}\n"
            f"Drawdown (7d): {_fmt_pct((market_snapshot.indicators or {}).get('drawdown_7d'))}"
        )
    catalyst_line = event.catalyst if event else "none identified"
    return (
        f"📊 *MARKET ANOMALY — {asset.ticker}*\n\n"
        f"{detail}\n\n"
        f"*Related catalyst:* {catalyst_line}\n"
        f"*Score:* {max(opportunity.long_score or 0, opportunity.short_score or 0)}/100\n"
    )


def render_breaking_wrapper(inner_body: str) -> str:
    """Wrap an already-rendered LONG/SHORT/MACRO body for the BREAKING
    channel -- used when a CRITICAL-tier opportunity is mirrored there
    (see app.workers.alerts.dispatch_one)."""
    return f"🚨 *BREAKING* 🚨\n\n{inner_body}"


def render_research_alert(opportunity: Opportunity, event: Event, raw_event: RawEvent) -> str:
    return (
        f"🔎 *RESEARCH*\n\n"
        f"*Catalyst:* {event.catalyst}\n"
        f"*Summary:* {event.reasoning_summary}\n"
        f"*Confidence:* {_confidence_bar(event.confidence)}\n"
        f"*Source:* {raw_event.url or raw_event.title}\n"
    )


def render_daily_briefing(
    now: datetime,
    macro: Optional[MacroSnapshot],
    top_opportunities: list[dict],
    watchlist: Sequence[str],
) -> str:
    """`top_opportunities` items: {"ticker", "opportunity_type", "score",
    "catalyst"} -- pre-resolved by app.workers.briefing so this stays a
    pure function with no DB access."""
    if macro is not None:
        macro_lines = (
            f"Fed funds {macro.fed_funds_rate}%  |  10Y {macro.treasury_10y}%  |  "
            f"VIX {macro.vix}  |  DXY {macro.dxy}  |  WTI ${macro.wti}"
        )
    else:
        macro_lines = "n/a (no macro snapshot yet)"

    if top_opportunities:
        dev_lines = "\n".join(
            f"  {i + 1}. *{o['ticker']}* ({o['opportunity_type']}, {o['score']}/100) — {o['catalyst']}"
            for i, o in enumerate(top_opportunities)
        )
    else:
        dev_lines = "  No opportunities above the watchlist threshold in the last 24h."

    watchlist_line = ", ".join(watchlist) if watchlist else "none"

    return (
        f"📋 *Daily Briefing — {now.strftime('%Y-%m-%d')}*\n\n"
        f"*Macro regime:*\n  {macro_lines}\n\n"
        f"*Major developments (last 24h):*\n{dev_lines}\n\n"
        f"*Watchlist:* {watchlist_line}\n\n"
        f"*Upcoming risks:* Review open theses and pending SEC filings via /theses and /events.\n"
    )
