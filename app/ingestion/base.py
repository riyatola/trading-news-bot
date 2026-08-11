"""Common ingestion adapter interface (Sprint 4).

Every source type (news API, SEC EDGAR, company IR RSS, and X in Sprint 7)
implements `SourceAdapter.fetch_events`, returning a list of
`NormalizedEvent`s in this shared shape. The polling worker
(`app.workers.news_ingestion`) doesn't need to know anything about a
source's underlying API -- it just calls `fetch_events`, catches
`IngestionError`, and persists whatever comes back as `raw_events` rows.
This keeps adding a new source (or swapping X's API for an RSS mirror per
the risk-mitigation plan) a matter of writing one adapter, not touching
the worker.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence


class IngestionError(Exception):
    """Base error for adapter fetch failures (network, auth, parse-shape).

    Adapters should wrap the underlying exception (e.g. NewsAPIError,
    SECEDGARError, RSSFeedError from app.exceptions) in this so the worker
    can apply uniform retry/dead-letter handling regardless of source.
    """


@dataclass(frozen=True)
class NormalizedEvent:
    """One story/filing/post, normalized to the shape `raw_events`
    expects (see app.db.models.RawEvent)."""

    source_name: str          # matches Source.name, e.g. "NewsAPI", "SEC EDGAR"
    source_type: str          # "news", "sec", "company_ir"
    source_event_id: str      # stable external id, used for de-dup on ingest
    published_at: datetime
    title: str
    content: str
    url: Optional[str] = None
    author: Optional[str] = None
    # External id for the specific account/author, if any (maps to
    # SourceAccount.account_id) -- e.g. a company's IR feed URL, or a
    # byline's author id once X is added in Sprint 7.
    source_account_external_id: Optional[str] = None
    language: str = "en"
    raw_metadata: dict = field(default_factory=dict)


class SourceAdapter(abc.ABC):
    """Base class for a pollable ingestion source."""

    source_name: str
    source_type: str

    @abc.abstractmethod
    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        """Fetch events published at/after `since` (None = source default
        lookback). Must raise IngestionError (or a subclass) on failure --
        never return a partial/silent empty list to mask an error."""
        raise NotImplementedError
