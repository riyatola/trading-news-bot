"""Company IR RSS adapter (Sprint 4).

Polls each tracked company's investor-relations RSS feed (URL stored on
`SourceAccount.url`, account_type="company_ir"; see scripts/seed_sources.py).
Chosen over scraping IR pages directly because RSS is stable and cheap to
add per company, and it doubles as the Tier-1 X fallback described in the
risk-mitigation plan (mirror company/CEO announcements via RSS if X access
is unavailable) once Sprint 7 wires X in behind the same adapter pattern.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

import feedparser

from app.exceptions import RSSFeedError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RSSFeedSource:
    company_name: str
    feed_url: str


class CompanyIRAdapter(SourceAdapter):
    source_name = "Company IR"
    source_type = "company_ir"

    def __init__(self, feeds: list[RSSFeedSource]):
        self._feeds = feeds

    @staticmethod
    def _stable_id(feed_url: str, entry_id: str) -> str:
        return hashlib.sha256(f"{feed_url}:{entry_id}".encode("utf-8")).hexdigest()[:32]

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        for feed_source in self._feeds:
            parsed = feedparser.parse(feed_source.feed_url)
            if parsed.bozo and not parsed.entries:
                # bozo=True with zero entries means the feed genuinely
                # failed to parse, as opposed to a minor XML quirk
                # feedparser recovered from anyway (bozo=True, entries
                # present). Only the former is worth retrying/dead-lettering.
                raise IngestionError(
                    RSSFeedError(
                        f"Failed to parse IR feed for {feed_source.company_name} "
                        f"({feed_source.feed_url}): {parsed.get('bozo_exception')}"
                    )
                )

            for entry in parsed.entries:
                published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                if not published_struct:
                    continue
                published_at = datetime(*published_struct[:6], tzinfo=timezone.utc).replace(tzinfo=None)
                if since is not None and published_at < since:
                    continue

                entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
                events.append(
                    NormalizedEvent(
                        source_name=self.source_name,
                        source_type=self.source_type,
                        source_event_id=self._stable_id(feed_source.feed_url, entry_id),
                        published_at=published_at,
                        title=entry.get("title", "").strip() or f"{feed_source.company_name} IR update",
                        content=entry.get("summary", "") or "",
                        url=entry.get("link"),
                        author=feed_source.company_name,
                        source_account_external_id=feed_source.feed_url,
                    )
                )

        logger.info("Fetched %d company IR RSS entries across %d feeds", len(events), len(self._feeds))
        return events
