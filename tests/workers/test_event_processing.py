from datetime import datetime

import pytest

from app.config.system_config import set_config_value
from app.db.models import Asset, Event, EventEntity, EventImpact, RawEvent, Source
from app.intelligence.openai_client import StructuredCompletionResult
from app.workers import event_processing

VALID_DATA = {
    "event_type": "earnings",
    "direction": "bullish",
    "severity": 7,
    "confidence": 85,
    "time_horizon": "days",
    "novelty": 60,
    "macro_relevance": 5,
    "catalyst": "Data center beat",
    "reasoning_summary": "Strong data center revenue drove the beat.",
    "impact_summary": "Likely positive reaction.",
    "macro_relevance_detail": None,
    "entities": [
        {"ticker": "NVDA", "relationship": "direct", "direction": "bullish",
         "impact": "Directly beat estimates.", "confidence": 90},
    ],
}


class FakeClient:
    def __init__(self, data=None):
        self._data = data or VALID_DATA
        self.calls = 0

    async def create_structured_completion(self, system_prompt, user_prompt, json_schema, schema_name):
        self.calls += 1
        return StructuredCompletionResult(data=self._data, prompt_tokens=100, completion_tokens=50)


def _seed_asset(db):
    asset = Asset(
        id="AST-01", ticker="NVDA", company_name="NVIDIA Corporation",
        mexc_symbol="NVDAUSDT", exchange_ticker="NASDAQ:NVDA",
        sector="Technology", industry="Semiconductors", country="US", currency="USD", active=True,
    )
    db.add(asset)
    db.commit()
    return asset


def _seed_source(db):
    source = Source(name="NewsAPI", source_type="news", credibility_tier=2, credibility_score=0.75)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _seed_pending_event(db, source, event_id, raw_id, content, cluster_id=None):
    raw = RawEvent(
        id=raw_id, source_id=source.id, published_at=datetime.utcnow(),
        title="NVIDIA beats Q3 estimates", content=content,
    )
    db.add(raw)
    db.commit()

    event = Event(id=event_id, raw_event_id=raw.id, event_cluster_id=cluster_id or f"CLU-{event_id}")
    db.add(event)
    db.commit()
    return event


LONG_CONTENT = "NVIDIA reported strong data center revenue growth well above analyst expectations for the quarter."


@pytest.mark.asyncio
async def test_analyzes_pending_event_and_persists_results(db):
    _seed_asset(db)
    source = _seed_source(db)
    event = _seed_pending_event(db, source, "EVT-1", "RAW-1", LONG_CONTENT)

    client = FakeClient()
    summary = await event_processing.process_pending_events(db, client)

    assert summary.analyzed == 1
    assert client.calls == 1

    db.refresh(event)
    assert event.processed_at is not None
    assert event.event_type == "earnings"
    assert event.direction == "bullish"

    entities = db.query(EventEntity).filter(EventEntity.event_id == event.id).all()
    assert len(entities) == 1
    assert entities[0].asset_id == "AST-01"

    impact = db.query(EventImpact).filter(EventImpact.event_id == event.id).first()
    assert impact is not None
    assert impact.summary == "Likely positive reaction."


@pytest.mark.asyncio
async def test_skips_events_with_insufficient_content(db):
    _seed_asset(db)
    source = _seed_source(db)
    event = _seed_pending_event(db, source, "EVT-2", "RAW-2", content="short")

    client = FakeClient()
    summary = await event_processing.process_pending_events(db, client)

    assert summary.skipped_insufficient_content == 1
    assert client.calls == 0

    db.refresh(event)
    assert event.processed_at is not None
    assert event.event_type is None


@pytest.mark.asyncio
async def test_reuses_cluster_sibling_without_calling_llm(db):
    _seed_asset(db)
    source = _seed_source(db)

    already_classified = _seed_pending_event(db, source, "EVT-3", "RAW-3", LONG_CONTENT, cluster_id="CLU-SHARED")
    already_classified.event_type = "earnings"
    already_classified.direction = "bullish"
    already_classified.severity = 7
    already_classified.processed_at = datetime.utcnow()
    already_classified.reasoning_summary = "Original analysis."
    db.commit()
    db.add(
        EventEntity(
            event_id=already_classified.id, asset_id="AST-01",
            relationship="direct", direction="bullish", impact="Beat estimates.", confidence=90,
        )
    )
    db.add(EventImpact(event_id=already_classified.id, summary="Original impact summary.", macro_relevance={}, cross_asset_effects=[]))
    db.commit()

    pending = _seed_pending_event(db, source, "EVT-4", "RAW-4", LONG_CONTENT, cluster_id="CLU-SHARED")

    client = FakeClient()
    summary = await event_processing.process_pending_events(db, client)

    assert summary.reused_from_cluster == 1
    assert client.calls == 0

    db.refresh(pending)
    assert pending.event_type == "earnings"
    assert "Reused from cluster sibling" in pending.reasoning_summary

    entities = db.query(EventEntity).filter(EventEntity.event_id == pending.id).all()
    assert len(entities) == 1


@pytest.mark.asyncio
async def test_stops_analyzing_once_daily_cap_exceeded(db):
    _seed_asset(db)
    source = _seed_source(db)
    set_config_value(db, "ai_daily_spend_cap_usd", 0.0)  # fail closed immediately

    event = _seed_pending_event(db, source, "EVT-5", "RAW-5", LONG_CONTENT)

    client = FakeClient()
    summary = await event_processing.process_pending_events(db, client)

    assert summary.analyzed == 0
    assert summary.queued_cap_exceeded == 1
    assert client.calls == 0

    db.refresh(event)
    assert event.processed_at is None  # left pending for next poll


@pytest.mark.asyncio
async def test_batch_size_limits_events_processed(db):
    _seed_asset(db)
    source = _seed_source(db)
    for i in range(5):
        _seed_pending_event(db, source, f"EVT-B{i}", f"RAW-B{i}", LONG_CONTENT, cluster_id=f"CLU-B{i}")

    client = FakeClient()
    summary = await event_processing.process_pending_events(db, client, batch_size=2)

    assert summary.analyzed == 2
    assert client.calls == 2

    remaining_pending = db.query(Event).filter(Event.processed_at.is_(None)).count()
    assert remaining_pending == 3
