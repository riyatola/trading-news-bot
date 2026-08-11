"""Alert decision logic (Sprint 6).

Maps an `Opportunity` row's score to a Telegram channel + tier, using
thresholds stored in `system_config` (per the project's "configurable
everything" principle -- see `app.config.system_config`) so an operator
can retune the 50/65/80/90 boundaries from the README without a deploy.

Kept as a pure function of (db config, opportunity) so it's easy to unit
test without standing up the full alert-dispatch worker, mirroring the
split between `app.intelligence.prefilter.decide` (a pure decision) and
`app.workers.event_processing` (the worker that acts on it).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from app.config.system_config import get_config_value
from app.db.models import Opportunity


class AlertTier(str, Enum):
    NONE = "none"
    WATCHLIST = "watchlist"
    OPPORTUNITY = "opportunity"
    HIGH_PRIORITY = "high_priority"
    CRITICAL = "critical"


class AlertChannel(str, Enum):
    BREAKING = "BREAKING"
    LONG = "LONG"
    SHORT = "SHORT"
    MACRO = "MACRO"
    MARKET = "MARKET"
    DAILY = "DAILY"
    RESEARCH = "RESEARCH"


@dataclass(frozen=True)
class AlertDecision:
    tier: AlertTier
    should_send: bool
    channel: Optional[AlertChannel]
    score: int


def _tier_for_score(score: int, thresholds: dict) -> AlertTier:
    if score >= thresholds["critical"]:
        return AlertTier.CRITICAL
    if score >= thresholds["high_priority"]:
        return AlertTier.HIGH_PRIORITY
    if score >= thresholds["opportunity"]:
        return AlertTier.OPPORTUNITY
    if score >= thresholds["watchlist"]:
        return AlertTier.WATCHLIST
    return AlertTier.NONE


def _load_thresholds(db: Session) -> dict:
    return {
        "watchlist": int(get_config_value(db, "alert_threshold_watchlist")),
        "opportunity": int(get_config_value(db, "alert_threshold_opportunity")),
        "high_priority": int(get_config_value(db, "alert_threshold_high_priority")),
        "critical": int(get_config_value(db, "alert_threshold_critical")),
    }


def decide(db: Session, opportunity: Opportunity) -> AlertDecision:
    """Decide whether/where to alert for `opportunity`.

    Below the watchlist threshold (<50 by default), nothing is sent.
    CRITICAL-tier LONG/SHORT/MACRO opportunities are *also* routed to
    BREAKING by the caller (`app.workers.alerts.dispatch_one`) in addition
    to their normal channel -- BREAKING exists specifically to surface the
    most urgent items regardless of underlying type.
    """
    thresholds = _load_thresholds(db)

    if opportunity.opportunity_type == "LONG":
        score = opportunity.long_score or 0
        channel = AlertChannel.LONG
    elif opportunity.opportunity_type == "SHORT":
        score = opportunity.short_score or 0
        channel = AlertChannel.SHORT
    elif opportunity.opportunity_type == "MACRO":
        score = opportunity.macro_score or 0
        channel = AlertChannel.MACRO
    elif opportunity.opportunity_type == "MARKET_ANOMALY":
        score = max(opportunity.long_score or 0, opportunity.short_score or 0)
        channel = AlertChannel.MARKET
    elif opportunity.opportunity_type == "BREAKING":
        score = max(opportunity.long_score or 0, opportunity.short_score or 0, opportunity.macro_score or 0)
        channel = AlertChannel.BREAKING
    else:  # THESIS_CHANGE and anything else unrecognized -> RESEARCH
        score = max(opportunity.long_score or 0, opportunity.short_score or 0, opportunity.macro_score or 0)
        channel = AlertChannel.RESEARCH

    tier = _tier_for_score(score, thresholds)
    should_send = tier != AlertTier.NONE

    return AlertDecision(
        tier=tier,
        should_send=should_send,
        channel=channel if should_send else None,
        score=score,
    )
