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

    # --- Sprint 7: X integration rollout ---
    "x_integration_enabled": (
        False,
        "ingestion",
        "Feature flag for the X (Twitter) adapter. Defaults off for "
        "gradual, monitored rollout per the project's risk-mitigation "
        "plan -- Tier-1 accounts' announcements are also mirrored via "
        "Company IR RSS regardless of this flag.",
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
