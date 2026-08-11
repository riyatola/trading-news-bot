"""X (Twitter) API v2 client (Sprint 7).

Uses the recent-search endpoint (`/2/tweets/search/recent`) filtered to a
configured set of usernames (Tier-1 accounts -- see
`app.ingestion.x.adapter.XAdapter`), mirroring the error-handling shape of
`app.ingestion.news.newsapi_client.NewsAPIClient` /
`app.ingestion.sec.edgar_client.SECEDGARClient`: network/shape failures
raise `XAPIError` so the adapter/worker can apply consistent
retry/dead-letter handling.

X access is inherently fragile (rate limits, API-tier changes, account
suspensions) -- per the project's risk-mitigation plan, this client is
never the *only* path to Tier-1 announcements. `XAdapter` runs alongside
`CompanyIRAdapter`'s RSS feeds for the same companies, so an X outage
degrades coverage (slower, RSS-only) rather than losing it (see
`app.workers.news_ingestion._build_default_adapters`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.exceptions import XAPIError

logger = logging.getLogger(__name__)

X_RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
DEFAULT_TIMEOUT_SECONDS = 15.0
# X's recent-search `query` param has a practical length cap; batch
# usernames to stay well under it, same reasoning as
# NewsAPIClient.QUERY_BATCH_SIZE.
USERNAME_BATCH_SIZE = 20
MAX_RESULTS_PER_PAGE = 100


@dataclass(frozen=True)
class XPost:
    post_id: str
    author_username: str
    author_id: str
    text: str
    created_at: datetime
    url: str


class XClient:
    def __init__(
        self,
        bearer_token: str,
        base_url: str = X_RECENT_SEARCH_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._bearer_token = bearer_token
        self._base_url = base_url
        self._timeout = timeout
        self._client = client  # injectable for testing

    @staticmethod
    def _batch(items: list[str], size: int) -> list[list[str]]:
        return [items[i:i + size] for i in range(0, len(items), size)]

    async def fetch_recent_posts(
        self, usernames: list[str], since: Optional[datetime] = None
    ) -> list[XPost]:
        """Fetch recent, non-retweet posts authored by any of `usernames`.

        Raises:
            XAPIError: on missing token, network failure, rate limiting,
                non-200 response, or an unexpected response shape.
        """
        if not self._bearer_token:
            raise XAPIError("X request skipped: no bearer token configured")
        if not usernames:
            return []

        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        all_posts: list[XPost] = []
        batches = self._batch(usernames, USERNAME_BATCH_SIZE)

        for batch in batches:
            from_clause = " OR ".join(f"from:{u}" for u in batch)
            params: dict = {
                "query": f"({from_clause}) -is:retweet",
                "max_results": MAX_RESULTS_PER_PAGE,
                "tweet.fields": "created_at,author_id",
                "expansions": "author_id",
                "user.fields": "username",
            }
            if since is not None:
                params["start_time"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

            try:
                if self._client is not None:
                    response = await self._client.get(
                        self._base_url, params=params, headers=headers, timeout=self._timeout
                    )
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            self._base_url, params=params, headers=headers, timeout=self._timeout
                        )
            except httpx.HTTPError as exc:
                raise XAPIError(f"X request failed: {exc}") from exc

            if response.status_code == 429:
                raise XAPIError("X rate limit exceeded (429)")
            if response.status_code != 200:
                raise XAPIError(f"X returned status {response.status_code}: {response.text[:200]}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise XAPIError("X returned invalid JSON") from exc

            users_by_id = {
                u["id"]: u.get("username", "")
                for u in (payload.get("includes") or {}).get("users", [])
            }

            for item in payload.get("data", []) or []:
                created_raw = item.get("created_at")
                if not created_raw or not item.get("id") or not item.get("text"):
                    continue
                try:
                    created_at = datetime.strptime(
                        created_raw, "%Y-%m-%dT%H:%M:%S.%fZ"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning("Discarding X post with unparseable created_at: %s", created_raw)
                    continue

                author_id = item.get("author_id", "")
                username = users_by_id.get(author_id, "")
                post_id = str(item["id"])
                all_posts.append(
                    XPost(
                        post_id=post_id,
                        author_username=username,
                        author_id=author_id,
                        text=item["text"],
                        created_at=created_at.replace(tzinfo=None),
                        url=f"https://x.com/{username}/status/{post_id}" if username else "",
                    )
                )

        logger.info("Fetched %d X posts across %d query batches", len(all_posts), len(batches))
        return all_posts
