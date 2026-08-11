"""X (Twitter) source adapter (Sprint 7): XClient -> NormalizedEvent.

Tier-1 only for v1 (company accounts, CEOs, regulators) per the project's
risk-mitigation plan -- Tier-2 (journalists/analysts) is a natural v2
follow-up once Tier-1 has run cleanly under monitoring for a while.
Accounts are stored as `SourceAccount` rows under the "x" source_type,
`account_type` in {"company", "ceo", "regulator"}, `account_id` = the
X username (see `app.workers.news_ingestion._build_default_adapters` for
how they're loaded, and `scripts/seed_sources.py`'s
`COMPANY_IR_FEEDS`-style pattern for how to seed them).

Gated behind the `x_integration_enabled` system_config flag (default
off) for gradual, monitored rollout -- see SPRINT7_NOTES.md.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from app.exceptions import XAPIError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.x.x_client import XClient


class XAdapter(SourceAdapter):
    source_name = "X"
    source_type = "x"

    def __init__(self, client: XClient, tier1_usernames: list[str]):
        self._client = client
        self._usernames = tier1_usernames

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        try:
            posts = await self._client.fetch_recent_posts(self._usernames, since=since)
        except XAPIError as exc:
            raise IngestionError(str(exc)) from exc

        return [
            NormalizedEvent(
                source_name=self.source_name,
                source_type=self.source_type,
                source_event_id=post.post_id,
                published_at=post.created_at,
                title=f"@{post.author_username}: {post.text[:80]}",
                content=post.text,
                url=post.url or None,
                author=post.author_username,
                source_account_external_id=post.author_id or post.author_username,
            )
            for post in posts
        ]
