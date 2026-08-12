"""Typed accessors for the `system_config` table (Sprint 5, extended by
Sprints 6-7).

Per the project's "configurable everything" principle (see README), AI
cost controls (Sprint 5), alert thresholds/routing (Sprint 6), and the X
integration rollout flag (Sprint 7) all live here rather than as bare
constants -- an operator can tune them (tighten the daily spend cap,
retune the 50/65/80/90 alert boundaries, flip X ingestion on) without a
deploy. Each key still has an in-code default (mirroring `Settings`'
defaults where relevant) so a fresh database with no seeded config rows
degrades gracefully instead of crashing -- run
`scripts/seed_system_config.py` to persist the defaults explicitly and
make them editable.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.models import SystemConfig

# key -> (default_value, category, description)
DEFAULTS: dict[str, tuple[Any, str, str]] = {
    "ai_daily_spend_cap_usd": (
        None,  # None => fall back to Settings.ai_daily_spend_cap_usd
        "ai_cost",
        "Max USD spent on LLM event analysis per UTC day before the "
        "event-processing worker queues remaining events for the next day.",
    ),
    "prefilter_min_content_length": (
        40,
        "ai_cost",
        "Raw events with fewer than this many characters of content are "
        "skipped before the LLM pre-filter gate (too little text to "
        "classify reliably).",
    ),
    "event_processing_batch_size": (
        None,  # None => fall back to Settings.event_processing_batch_size
        "ai_cost",
        "Number of pending events processed per event-processing poll cycle.",
    ),

    # --- Sprint 6: alert thresholds + routing ---
    "alert_threshold_watchlist": (
        50,
        "alerts",
        "Minimum opportunity score to trigger a WATCHLIST-tier alert "
        "(below this, no alert is sent).",
    ),
    "alert_threshold_opportunity": (
        65,
        "alerts",
        "Minimum opportunity score to trigger an OPPORTUNITY-tier alert.",
    ),
    "alert_threshold_high_priority": (
        80,
        "alerts",
        "Minimum opportunity score to trigger a HIGH-PRIORITY-tier alert.",
    ),
    "alert_threshold_critical": (
        90,
        "alerts",
        "Minimum opportunity score to trigger a CRITICAL-tier alert; "
        "CRITICAL LONG/SHORT/MACRO opportunities are also mirrored to "
        "the BREAKING channel.",
    ),
    "telegram_channel_map": (
        {},
        "alerts",
        "Optional {channel: {chat_id, message_thread_id}} overrides per "
        "Telegram channel (BREAKING/LONG/SHORT/MACRO/MARKET/DAILY/"
        "RESEARCH). Falls back to Settings.telegram_chat_id with no "
        "topic for any channel not listed here.",
    ),

    # --- Sprint 7: social + alternative-signal integrations ---
    # X (Twitter) is intentionally deprecated. X's API is expensive,
    # fragile, and easily replaced by the 4 sources below.
    # IMPORTANT (Aug 2026 reality check):
    #   * StockTwits closed NEW developer signups per api.stocktwits.com/
    #     developers. The adapter still works if you already have a token,
    #     but new users should use ApeWisdom + Finnhub Social instead.
    #   * Quiver Quantitative no longer has a free API tier (now $30/mo
    #     minimum). Still valuable for regulatory signals, but not free.
    #
    # Truly free + actually-signup-able replacements (recommended):
    #   1) Finnhub Social Sentiment (gate: finnhub_social_sentiment_enabled)
    #      -- free on your existing FINNHUB_API_KEY plan. Reddit + X
    #      mention counts + per-ticker -1..1 sentiment score. Zero extra cost.
    #   2) ApeWisdom (gate: apewisdom_integration_enabled) -- free, no
    #      signup, no API key. Top-ranked WSB + 4chan mention counts with
    #      bull/bear/SPY proportions and 24h rank change.
    #   3) Reddit (gate: reddit_integration_enabled) -- raw r/wallstreetbets,
    #      r/stocks, r/investing newest-post streams, ticker-extracted.
    #   4) StockTwits (gate: stocktwits_integration_enabled) -- adapter
    #      works, but NEW signups are closed as of Aug 2026. Left in place
    #      for legacy token holders.
    #   5) Quiver Quantitative (gate: quiver_quant_integration_enabled)
    #      -- paid-only now (congress trades, insider trades, WSB aggregates,
    #      Google Trends). Worth it for the unique regulatory signals.
    "stocktwits_integration_enabled": (
        False,
        "ingestion",
        "Feature flag for the StockTwits adapter (ticker-scoped finance "
        "social streams with native bullish/bearish tags). NOTE: StockTwits "
        "CLOSED new developer signups as of Aug 2026. Only enable if you "
        "already have a legacy STOCKTWITS_ACCESS_TOKEN. Otherwise use "
        "ApeWisdom + Finnhub Social instead (free, actually signup-able).",
    ),
    "reddit_integration_enabled": (
        False,
        "ingestion",
        "Feature flag for the Reddit adapter (retail sentiment via "
        "r/wallstreetbets, r/stocks, r/investing). Free OAuth tier, 60 "
        "req/min. Requires REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET + "
        "REDDIT_USER_AGENT (create a 'script' app at reddit.com/prefs/apps).",
    ),
    "quiver_quant_integration_enabled": (
        False,
        "ingestion",
        "Feature flag for the Quiver Quantitative adapter (congress "
        "trades, insider trades, WSB sentiment, Google Trends). NOTE: "
        "Quiver no longer has a free API tier (min ~$30/mo as of Aug 2026). "
        "Requires QUIVER_QUANT_API_KEY. Worth it for the unique regulatory "
        "signals; otherwise use ApeWisdom + Reddit for free WSB coverage.",
    ),
    "apewisdom_integration_enabled": (
        True,
        "ingestion",
        "Feature flag for the ApeWisdom adapter (r/wallstreetbets + 4chan "
        "mention counts, rank deltas, bull/bear/SPY proportions). Free, "
        "no signup, no API key needed -- just flip this flag on. "
        "Replaces the StockTwits direct adapter for new deployments "
        "(StockTwits closed new signups Aug 2026).",
    ),
    "finnhub_social_sentiment_enabled": (
        True,
        "ingestion",
        "Enable Finnhub /stock/social-sentiment endpoint alongside the "
        "company-news stream. Uses your existing FINNHUB_API_KEY at zero "
        "extra cost (1 extra request/ticker per poll; 60 req/min free pool "
        "covers news + social comfortably). Emits per-ticker Reddit + X "
        "mention counts and a weighted -1..1 sentiment score. On by default "
        "because it's the cheapest, highest-signal social source in the stack.",
    ),
    "x_integration_enabled": (
        False,
        "ingestion",
        "DEPRECATED. X (Twitter) integration has been replaced by "
        "Finnhub Social Sentiment + ApeWisdom + Reddit + Quiver. X's API "
        "is expensive (~$200/mo Basic), fragile, and the alternatives cover "
        "more signal types for $0-30/mo total. Leave this flag off.",
    ),
}


def get_config_value(db: Session, key: str) -> Any:
    """Return the configured value for `key`, falling back to its in-code
    default (and, for a couple of keys, to `Settings`) if no row exists."""
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is not None:
        return row.value

    if key not in DEFAULTS:
        raise KeyError(f"Unknown system_config key: {key}")
    default, _category, _description = DEFAULTS[key]

    settings = get_settings()
    if key == "ai_daily_spend_cap_usd" and default is None:
        return settings.ai_daily_spend_cap_usd
    if key == "event_processing_batch_size" and default is None:
        return settings.event_processing_batch_size
    return default


def set_config_value(db: Session, key: str, value: Any) -> SystemConfig:
    """Upsert a system_config row for `key`."""
    if key not in DEFAULTS:
        raise KeyError(f"Unknown system_config key: {key}")
    _default, category, description = DEFAULTS[key]

    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        row = SystemConfig(key=key, value=value, category=category, description=description)
        db.add(row)
    else:
        row.value = value
    db.commit()
    db.refresh(row)
    return row
