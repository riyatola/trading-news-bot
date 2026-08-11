"""Daily AI spend tracking + cap enforcement (Sprint 5).

Every successful LLM analysis call is logged to `ai_spend_log`
(append-only, mirrors `raw_events`' immutability). Before each call the
event-processing worker checks `is_daily_cap_exceeded` against the
configured cap (system_config key 'ai_daily_spend_cap_usd', falling back
to `Settings.ai_daily_spend_cap_usd`); once exceeded, remaining pending
events for the cycle are left unprocessed (processed_at stays None) so
they're picked up automatically once the next UTC day's spend resets --
the "queue fallback" behavior called out in the project's risk-mitigation
plan, as opposed to dropping them or failing the whole poll.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config.system_config import get_config_value
from app.db.models import AISpendLog
from app.intelligence.pricing import TokenUsage, estimate_cost_usd


def _utc_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def get_daily_spend_usd(db: Session, now: datetime | None = None) -> float:
    """Sum of `cost_usd` logged so far for the current UTC day."""
    now = now or datetime.utcnow()
    start, end = _utc_day_bounds(now)
    rows = (
        db.query(AISpendLog.cost_usd)
        .filter(AISpendLog.created_at >= start, AISpendLog.created_at < end)
        .all()
    )
    return round(sum(r[0] for r in rows), 6)


def get_daily_cap_usd(db: Session) -> float:
    return float(get_config_value(db, "ai_daily_spend_cap_usd"))


def is_daily_cap_exceeded(db: Session, now: datetime | None = None) -> bool:
    cap = get_daily_cap_usd(db)
    if cap <= 0:
        # A non-positive cap means "AI analysis disabled" rather than
        # "unlimited" -- fail closed.
        return True
    return get_daily_spend_usd(db, now=now) >= cap


def record_spend(
    db: Session,
    event_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> AISpendLog:
    """Log one completed LLM call's cost. Caller is responsible for
    committing the surrounding transaction (mirrors how callers of
    `app.workers.news_ingestion.persist_normalized_event` manage commits)."""
    cost = estimate_cost_usd(model, TokenUsage(prompt_tokens, completion_tokens))
    row = AISpendLog(
        event_id=event_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
