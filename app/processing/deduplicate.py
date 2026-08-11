"""Event deduplication (Sprint 4).

Clusters raw events that describe the same underlying story so downstream
scoring/alerting doesn't double-count it (e.g. the same earnings beat
reported by three wire services within minutes of each other). Runs
immediately after a raw event is persisted (see
`app.workers.news_ingestion.persist_normalized_event`), creating the
corresponding `Event` stub row. AI classification (event_type, direction,
severity, ...) is filled in later by Sprint 5's processing step --
`processed_at` stays None here so that step can find pending rows.

Approach: for each new raw event, compare its normalized title against
recent Event rows (joined to their RawEvent) within DEDUP_WINDOW using
Jaccard token similarity. Above SIMILARITY_THRESHOLD, reuse that Event's
event_cluster_id; otherwise mint a new cluster id. This is a cheap,
explainable first pass -- no embeddings/LLM calls, consistent with the
project's "pre-filter before paying for AI" cost posture (Sprint 5 spends
LLM budget on classification, not dedup).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.db.models import Event, RawEvent
from app.processing.normalize import title_tokens

DEDUP_WINDOW = timedelta(hours=72)
SIMILARITY_THRESHOLD = 0.6


@dataclass(frozen=True)
class ClusterCandidate:
    """A recent (title, cluster id) pair to compare a new raw event
    against. Kept as a plain dataclass (rather than passing ORM rows
    around) so `assign_cluster_id` is a pure function, easy to unit test
    without a DB -- mirrors the pattern in app.market.indicators."""

    event_cluster_id: str
    title: str
    published_at: datetime


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def load_recent_clusters(
    db: Session, before: datetime, window: timedelta = DEDUP_WINDOW
) -> list[ClusterCandidate]:
    """Recent (RawEvent.title, Event.event_cluster_id) pairs to compare a
    new raw event against, newest first."""
    cutoff = before - window
    rows = (
        db.query(Event.event_cluster_id, RawEvent.title, RawEvent.published_at)
        .join(RawEvent, Event.raw_event_id == RawEvent.id)
        .filter(RawEvent.published_at >= cutoff, RawEvent.published_at <= before)
        .order_by(RawEvent.published_at.desc())
        .all()
    )
    return [
        ClusterCandidate(event_cluster_id=r[0], title=r[1], published_at=r[2])
        for r in rows
        if r[0] is not None
    ]


def assign_cluster_id(
    raw_event,
    candidates: Sequence[ClusterCandidate],
    threshold: float = SIMILARITY_THRESHOLD,
) -> str:
    """Return an existing cluster id for a near-duplicate story, or mint a
    new one. `raw_event` only needs a `.title` attribute (accepts a real
    RawEvent or any title-bearing stand-in for testing). `candidates`
    should already be scoped to the dedup window (see
    `load_recent_clusters`) -- this function is pure so it's easy to unit
    test without a DB.
    """
    new_tokens = title_tokens(raw_event.title)
    best_score = 0.0
    best_cluster: Optional[str] = None

    for candidate in candidates:
        score = jaccard_similarity(new_tokens, title_tokens(candidate.title))
        if score > best_score:
            best_score = score
            best_cluster = candidate.event_cluster_id

    if best_cluster is not None and best_score >= threshold:
        return best_cluster
    return f"CLU-{uuid.uuid4().hex[:16]}"


def deduplicate_and_create_event(db: Session, raw_event: RawEvent) -> Event:
    """Assign a cluster id to `raw_event` and create its (unclassified)
    Event stub row.
    """
    candidates = load_recent_clusters(db, before=raw_event.published_at)
    cluster_id = assign_cluster_id(raw_event, candidates)

    event = Event(
        id=f"EVT-{uuid.uuid4().hex[:20]}",
        event_cluster_id=cluster_id,
        raw_event_id=raw_event.id,
        processed_at=None,
        is_reprocessable=True,
    )
    db.add(event)
    db.commit()
    return event
