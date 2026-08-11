from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, DeadLetterEvent, RawEvent
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.workers.news_ingestion import persist_normalized_event, poll_adapter


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class _AlwaysFailsAdapter(SourceAdapter):
    source_name = "Flaky Source"
    source_type = "news"

    async def fetch_events(self, since=None):
        raise IngestionError("simulated upstream failure")


class _WorksAdapter(SourceAdapter):
    source_name = "Reliable Source"
    source_type = "news"

    def __init__(self, events):
        self._events = events

    async def fetch_events(self, since=None):
        return self._events


def _sample_event(source_event_id: str = "abc123") -> NormalizedEvent:
    return NormalizedEvent(
        source_name="Reliable Source",
        source_type="news",
        source_event_id=source_event_id,
        published_at=datetime.utcnow(),
        title="Sample Corp announces new product",
        content="Sample Corp today announced...",
        url="https://example.com/article",
        author="Jane Reporter",
    )


@pytest.mark.asyncio
async def test_poll_adapter_dead_letters_after_max_retries(db_session):
    adapter = _AlwaysFailsAdapter()

    persisted_count = await poll_adapter(db_session, adapter, since=None)

    assert persisted_count == 0
    dead_letters = db_session.query(DeadLetterEvent).all()
    assert len(dead_letters) == 1
    assert dead_letters[0].source_name == "Flaky Source"
    assert dead_letters[0].attempts == 3


@pytest.mark.asyncio
async def test_poll_adapter_persists_events_on_success(db_session):
    adapter = _WorksAdapter([_sample_event()])

    persisted_count = await poll_adapter(db_session, adapter, since=None)

    assert persisted_count == 1
    assert db_session.query(RawEvent).count() == 1
    assert db_session.query(DeadLetterEvent).count() == 0


def test_persist_normalized_event_is_idempotent_on_duplicate(db_session):
    event = _sample_event()

    first = persist_normalized_event(db_session, event)
    second = persist_normalized_event(db_session, event)

    assert first is not None
    assert second is None  # duplicate (source_id, source_event_id) -> skipped
    assert db_session.query(RawEvent).count() == 1
