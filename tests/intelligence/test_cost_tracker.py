from datetime import datetime, timedelta

from app.db.models import Asset, Event, RawEvent, Source
from app.intelligence import cost_tracker


def _make_event(db, event_id="EVT-1"):
    source = Source(name="NewsAPI", source_type="news", credibility_tier=2, credibility_score=0.75)
    db.add(source)
    db.commit()
    db.refresh(source)

    raw = RawEvent(
        id=f"RAW-{event_id}",
        source_id=source.id,
        published_at=datetime.utcnow(),
        title="Some headline",
        content="Some content long enough to pass any prefilter checks easily.",
    )
    db.add(raw)
    db.commit()

    event = Event(id=event_id, raw_event_id=raw.id, event_cluster_id=f"CLU-{event_id}")
    db.add(event)
    db.commit()
    return event


def test_record_spend_persists_and_sums(db):
    event = _make_event(db)
    cost_tracker.record_spend(db, event_id=event.id, model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
    cost_tracker.record_spend(db, event_id=event.id, model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)

    total = cost_tracker.get_daily_spend_usd(db)
    assert total > 0
    # Two identical calls should sum to double one call's cost.
    single = cost_tracker.get_daily_spend_usd(db, now=datetime.utcnow()) / 2
    assert round(total, 6) == round(single * 2, 6)


def test_spend_from_a_different_utc_day_is_excluded(db):
    event = _make_event(db)
    row = cost_tracker.record_spend(
        db, event_id=event.id, model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500
    )
    # Backdate the log entry to yesterday.
    row.created_at = datetime.utcnow() - timedelta(days=1)
    db.commit()

    assert cost_tracker.get_daily_spend_usd(db) == 0.0


def test_cap_not_exceeded_when_under_cap(db):
    event = _make_event(db)
    cost_tracker.record_spend(db, event_id=event.id, model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
    # Default cap (from Settings) is 100.0 -- nowhere near exceeded by one call.
    assert cost_tracker.is_daily_cap_exceeded(db) is False


def test_cap_exceeded_once_spend_crosses_configured_cap(db):
    from app.config.system_config import set_config_value

    set_config_value(db, "ai_daily_spend_cap_usd", 0.0005)
    event = _make_event(db)
    cost_tracker.record_spend(
        db, event_id=event.id, model="gpt-4o-mini", prompt_tokens=100000, completion_tokens=100000
    )
    assert cost_tracker.is_daily_cap_exceeded(db) is True


def test_non_positive_cap_fails_closed(db):
    from app.config.system_config import set_config_value

    set_config_value(db, "ai_daily_spend_cap_usd", 0)
    assert cost_tracker.is_daily_cap_exceeded(db) is True
