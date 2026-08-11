"""NewsAPI source adapter (Sprint 4): NewsAPIClient -> NormalizedEvent."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional, Sequence

from app.exceptions import NewsAPIError
from app.ingestion.base import IngestionError, NormalizedEvent, SourceAdapter
from app.ingestion.news.newsapi_client import NewsAPIClient


class NewsAdapter(SourceAdapter):
    source_name = "NewsAPI"
    source_type = "news"

    def __init__(self, client: NewsAPIClient, company_names: list[str]):
        self._client = client
        self._company_names = company_names

    @staticmethod
    def _stable_id(url: str) -> str:
        """Deterministic id for de-dup on ingest: NewsAPI doesn't expose a
        stable article id, so hash the (effectively unique) article URL."""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    async def fetch_events(self, since: Optional[datetime] = None) -> Sequence[NormalizedEvent]:
        try:
            articles = await self._client.fetch_articles(self._company_names, since=since)
        except NewsAPIError as exc:
            raise IngestionError(str(exc)) from exc

        return [
            NormalizedEvent(
                source_name=article.source_name,
                source_type=self.source_type,
                source_event_id=self._stable_id(article.url),
                published_at=article.published_at,
                title=article.title,
                content=article.content or article.description or "",
                url=article.url,
                author=article.author,
            )
            for article in articles
        ]
