"""Pre-filter gate (Sprint 5).

Cheap, rule-based checks that run before an event is ever handed to the
LLM -- consistent with the project's "pre-filter before paying for AI"
cost posture (see `app.processing.deduplicate`'s module docstring, which
applies the same philosophy to dedup). Two independent savings:

1. **Insufficient content**: a raw event with too little text can't be
   classified reliably anyway, so skip the LLM call entirely rather than
   spend tokens on a low-confidence guess.
2. **Cluster reuse**: `app.processing.deduplicate` already groups
   near-duplicate stories (the same earnings beat reported by three wire
   services) under one `event_cluster_id`. If another event in the same
   cluster has *already* been classified, its analysis almost certainly
   applies here too -- copy it instead of re-running the LLM on
   substantively the same text.

Both checks are pure/DB-read-only and return a `PrefilterDecision` that
`app.workers.event_processing` acts on; nothing here writes to the DB.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from app.config.system_config import get_config_value
from app.db.models import Event, RawEvent


class PrefilterAction(str, Enum):
    SKIP_INSUFFICIENT_CONTENT = "skip_insufficient_content"
    REUSE_CLUSTER = "reuse_cluster"
    ANALYZE = "analyze"


@dataclass(frozen=True)
class PrefilterDecision:
    action: PrefilterAction
    # Populated only for REUSE_CLUSTER -- the already-classified sibling
    # event whose analysis should be copied.
    reuse_source: Optional[Event] = None
    reason: str = ""


def has_sufficient_content(raw_event: RawEvent, min_length: int) -> bool:
    text = f"{raw_event.title or ''} {raw_event.content or ''}".strip()
    return len(text) >= min_length


def find_classified_cluster_sibling(db: Session, event: Event) -> Optional[Event]:
    """A different, already-classified Event sharing `event.event_cluster_id`,
    most-recently-processed first. None if this event has no cluster id
    (shouldn't happen post-dedup, but defensive) or no sibling qualifies."""
    if not event.event_cluster_id:
        return None
    return (
        db.query(Event)
        .filter(
            Event.event_cluster_id == event.event_cluster_id,
            Event.id != event.id,
            Event.processed_at.isnot(None),
            Event.event_type.isnot(None),  # actually classified, not a prior skip
        )
        .order_by(Event.processed_at.desc())
        .first()
    )


def decide(db: Session, event: Event, raw_event: RawEvent) -> PrefilterDecision:
    """Run the pre-filter gate for one pending event."""
    min_length = int(get_config_value(db, "prefilter_min_content_length"))
    if not has_sufficient_content(raw_event, min_length):
        return PrefilterDecision(
            action=PrefilterAction.SKIP_INSUFFICIENT_CONTENT,
            reason=f"Content shorter than {min_length} chars; not worth an LLM call.",
        )

    sibling = find_classified_cluster_sibling(db, event)
    if sibling is not None:
        return PrefilterDecision(
            action=PrefilterAction.REUSE_CLUSTER,
            reuse_source=sibling,
            reason=f"Reusing classification from sibling event {sibling.id} in the same cluster.",
        )

    return PrefilterDecision(action=PrefilterAction.ANALYZE)
