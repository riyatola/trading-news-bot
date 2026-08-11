"""NewsAPI.org client (Sprint 4).

Thin REST wrapper, mirroring the error-handling shape of
`app.market.mexc.MEXCClient`: network/shape failures raise `NewsAPIError`
so the adapter/worker can apply consistent retry/dead-letter handling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.exceptions import NewsAPIError

logger = logging.getLogger(__name__)

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
DEFAULT_TIMEOUT_SECONDS = 10.0
# NewsAPI's `q` accepts boolean OR groups but has a practical length cap;
# batch tracked company names to stay well under it rather than issuing
# one request per company (52 assets x every-few-minutes would burn
# through NewsAPI's rate limit fast).
QUERY_BATCH_SIZE = 20


@dataclass(frozen=True)
class NewsAPIArticle:
    source_name: str
    author: Optional[str]
    title: str
    description: Optional[str]
    content: Optional[str]
    url: str
    published_at: datetime


class NewsAPIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = NEWSAPI_EVERYTHING_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._client = client  # injectable for testing

    @staticmethod
    def _batch(items: list[str], size: int) -> list[list[str]]:
        return [items[i:i + size] for i in range(0, len(items), size)]

    async def fetch_articles(
        self,
        company_names: list[str],
        since: Optional[datetime] = None,
        page_size: int = 100,
    ) -> list[NewsAPIArticle]:
        """Fetch recent articles mentioning any of `company_names`.

        Raises:
            NewsAPIError: on network failure, non-200 response, or an
                unexpected response shape.
        """
        if not self._api_key:
            raise NewsAPIError("NewsAPI request skipped: no API key configured")
        if not company_names:
            return []

        all_articles: list[NewsAPIArticle] = []
        batches = self._batch(company_names, QUERY_BATCH_SIZE)

        for batch in batches:
            query = " OR ".join(f'"{name}"' for name in batch)
            params = {
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": page_size,
                "apiKey": self._api_key,
            }
            if since is not None:
                params["from"] = since.strftime("%Y-%m-%dT%H:%M:%S")

            try:
                if self._client is not None:
                    response = await self._client.get(self._base_url, params=params, timeout=self._timeout)
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(self._base_url, params=params, timeout=self._timeout)
            except httpx.HTTPError as exc:
                raise NewsAPIError(f"NewsAPI request failed: {exc}") from exc

            if response.status_code != 200:
                raise NewsAPIError(
                    f"NewsAPI returned status {response.status_code}: {response.text[:200]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise NewsAPIError("NewsAPI returned invalid JSON") from exc

            if payload.get("status") != "ok":
                raise NewsAPIError(f"NewsAPI error response: {payload.get('message', 'unknown error')}")

            for item in payload.get("articles", []) or []:
                published_raw = item.get("publishedAt")
                if not published_raw or not item.get("url") or not item.get("title"):
                    continue
                try:
                    published_at = datetime.strptime(
                        published_raw, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning("Discarding NewsAPI article with unparseable publishedAt: %s", published_raw)
                    continue

                source = item.get("source") or {}
                all_articles.append(
                    NewsAPIArticle(
                        source_name=source.get("name") or "NewsAPI",
                        author=item.get("author"),
                        title=item["title"],
                        description=item.get("description"),
                        content=item.get("content") or item.get("description") or "",
                        url=item["url"],
                        published_at=published_at.replace(tzinfo=None),
                    )
                )

        logger.info(
            "Fetched %d NewsAPI articles across %d query batches",
            len(all_articles), len(batches),
        )
        return all_articles
