from datetime import datetime

from app.db.models import Event, RawEvent, Source
from app.intelligence.prefilter import PrefilterAction, decide, has_sufficient_content


def _make_source(db):
    source = Source(name="NewsAPI", source_type="news", credibility_tier=2, credibility_score=0.75)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _make_raw_event(db, source, raw_id, content):
    raw = RawEvent(
        id=raw_id,
        source_id=source.id,
        published_at=datetime.utcnow(),
        title="Headline",
        content=content,
    )
    db.add(raw)
    db.commit()
    return raw


def test_has_sufficient_content_true_when_long_enough():
    class Fake:
        title = "Apple beats earnings"
        content = "Apple reported quarterly earnings that beat analyst expectations by a wide margin."

    assert has_sufficient_content(Fake(), min_length=40) is True


def test_has_sufficient_content_false_when_too_short():
    class Fake:
        title = "Apple"
        content = ""

    assert has_sufficient_content(Fake(), min_length=40) is False


def test_decide_skips_insufficient_content(db):
    source = _make_source(db)
    raw = _make_raw_event(db, source, "RAW-1", content="short")
    event = Event(id="EVT-1", raw_event_id=raw.id, event_cluster_id="CLU-1")
    db.add(event)
    db.commit()

    decision = decide(db, event, raw)
    assert decision.action == PrefilterAction.SKIP_INSUFFICIENT_CONTENT


def test_decide_analyzes_when_content_sufficient_and_no_sibling(db):
    source = _make_source(db)
    raw = _make_raw_event(
        db, source, "RAW-2",
        content="A sufficiently long article body describing a material corporate event in detail.",
    )
    event = Event(id="EVT-2", raw_event_id=raw.id, event_cluster_id="CLU-2")
    db.add(event)
    db.commit()

    decision = decide(db, event, raw)
    assert decision.action == PrefilterAction.ANALYZE


def test_decide_reuses_classified_cluster_sibling(db):
    source = _make_source(db)
    long_content = "A sufficiently long article body describing a material corporate event in detail."

    raw1 = _make_raw_event(db, source, "RAW-3", content=long_content)
    sibling = Event(
        id="EVT-3",
        raw_event_id=raw1.id,
        event_cluster_id="CLU-3",
        event_type="earnings",
        processed_at=datetime.utcnow(),
    )
    db.add(sibling)
    db.commit()

    raw2 = _make_raw_event(db, source, "RAW-4", content=long_content)
    event = Event(id="EVT-4", raw_event_id=raw2.id, event_cluster_id="CLU-3")
    db.add(event)
    db.commit()

    decision = decide(db, event, raw2)
    assert decision.action == PrefilterAction.REUSE_CLUSTER
    assert decision.reuse_source.id == "EVT-3"


def test_decide_ignores_unclassified_sibling(db):
    """A sibling that's processed but was itself a content-skip (no
    event_type) shouldn't be reused -- there's nothing to copy."""
    source = _make_source(db)
    long_content = "A sufficiently long article body describing a material corporate event in detail."

    raw1 = _make_raw_event(db, source, "RAW-5", content="short")
    skipped_sibling = Event(
        id="EVT-5",
        raw_event_id=raw1.id,
        event_cluster_id="CLU-5",
        event_type=None,
        processed_at=datetime.utcnow(),
    )
    db.add(skipped_sibling)
    db.commit()

    raw2 = _make_raw_event(db, source, "RAW-6", content=long_content)
    event = Event(id="EVT-6", raw_event_id=raw2.id, event_cluster_id="CLU-5")
    db.add(event)
    db.commit()

    decision = decide(db, event, raw2)
    assert decision.action == PrefilterAction.ANALYZE
