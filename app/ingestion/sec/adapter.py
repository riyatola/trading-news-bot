"""SEC EDGAR source adapter (Sprint 4): SECEDGARClient -> NormalizedEvent."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from app.exceptions import SECEDGARError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.sec.edgar_client import SECEDGARClient


class SECAdapter(SourceAdapter):
    source_name = "SEC EDGAR"
    source_type = "sec"

    def __init__(self, client: SECEDGARClient, company_names: list[str]):
        self._client = client
        self._company_names = company_names

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        try:
            filings = await self._client.search_filings(self._company_names, since=since)
        except SECEDGARError as exc:
            raise IngestionError(str(exc)) from exc

        return [
            NormalizedEvent(
                source_name=self.source_name,
                source_type=self.source_type,
                # accession_no is SEC's own stable filing id -- no hashing needed.
                source_event_id=filing.accession_no,
                published_at=filing.filed_at,
                title=f"{filing.company_name} files {filing.form_type}",
                content=filing.snippet,
                url=filing.url or None,
                author=None,
            )
            for filing in filings
        ]
