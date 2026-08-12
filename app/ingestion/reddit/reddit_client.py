"""Reddit OAuth read-only client (Sprint 7: retail sentiment, subreddit streams).

Uses the standard "script" OAuth2 client-credentials flow to get a
short-lived bearer token, then polls `/r/{sub}/new.json` (newest posts)
per configured subreddit. The 3 subreddits covered by default
(r/wallstreetbets, r/stocks, r/investing) are the highest retail
signal/noise ratio for the alert system.

Ticker extraction happens at the *adapter* layer, not the client -- the
client returns raw RedditPost objects with title/selftext intact, and
`RedditAdapter` runs the $TICKER regex against them to extract
mentioned tickers and drop posts with no tracked-asset mentions.

Mirrors the same error-handling shape as every other ingestion client:
network/auth/rate-limit/shape failures raise `RedditAPIError` so the
adapter/worker can apply consistent retry/dead-letter handling.

Rate limits: Reddit's free tier is approx 60 requests/minute per OAuth
client; 3 subreddits × 1 poll/cycle leaves enormous headroom.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.exceptions import RedditAPIError

logger = logging.getLogger(__name__)

REDDIT_OAUTH_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_SUB_NEW_TEMPLATE = "https://oauth.reddit.com/r/{sub}/new.json"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")
DEFAULT_POSTS_PER_SUB = 50
TOKEN_LIFETIME_BUFFER_SECONDS = 60  # refresh a bit early to avoid expiry mid-batch


@dataclass(frozen=True)
class RedditPost:
    post_id: str
    subreddit: str
    title: str
    selftext: str
    created_at: datetime
    author_username: str
    url: str
    score: int
    num_comments: int
    permalink: str


class RedditClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        base_url_template: str = REDDIT_SUB_NEW_TEMPLATE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._base_url_template = base_url_template
        self._timeout = timeout
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

        self._bearer_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def __aenter__(self) -> "RedditClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _refresh_bearer_token(self) -> str:
        if not self._client_id or not self._client_secret:
            raise RedditAPIError("Reddit request skipped: client_id or client_secret not configured")
        if not self._user_agent:
            raise RedditAPIError(
                "Reddit request skipped: user_agent not configured; Reddit requires a "
                "descriptive user agent (e.g. 'MarketIntelBot/0.1 by YourRedditUsername')."
            )

        now = datetime.utcnow()
        if (
            self._bearer_token is not None
            and self._token_expires_at is not None
            and now < self._token_expires_at
        ):
            return self._bearer_token

        auth = httpx.BasicAuth(self._client_id, self._client_secret)
        headers = {"User-Agent": self._user_agent}
        data = {"grant_type": "client_credentials"}
        try:
            response = await self._client.post(
                REDDIT_OAUTH_URL, auth=auth, headers=headers, data=data, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise RedditAPIError(f"Reddit OAuth request failed: {exc}") from exc

        if response.status_code != 200:
            raise RedditAPIError(
                f"Reddit OAuth failed (status {response.status_code}): {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RedditAPIError("Reddit OAuth returned invalid JSON") from exc

        token = payload.get("access_token")
        if not token:
            raise RedditAPIError(f"Reddit OAuth response missing access_token: {payload}")

        expires_in = int(payload.get("expires_in", 3600))
        self._bearer_token = token
        self._token_expires_at = now + timedelta(seconds=expires_in - TOKEN_LIFETIME_BUFFER_SECONDS)
        return token

    async def fetch_sub_new(
        self,
        subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
        limit_per_sub: int = DEFAULT_POSTS_PER_SUB,
        since: Optional[datetime] = None,
    ) -> list[RedditPost]:
        """Fetch the newest `limit_per_sub` posts from each subreddit.

        Client-side filters out posts older than `since` when provided.
        """
        if not subreddits:
            return []

        token = await self._refresh_bearer_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": self._user_agent,
        }
        all_posts: list[RedditPost] = []

        for sub in subreddits:
            url = self._base_url_template.format(sub=sub)
            params = {"limit": limit_per_sub, "raw_json": 1}
            try:
                response = await self._client.get(url, headers=headers, params=params, timeout=self._timeout)
            except httpx.HTTPError as exc:
                raise RedditAPIError(f"Reddit request failed for r/{sub}: {exc}") from exc

            if response.status_code == 429:
                raise RedditAPIError("Reddit rate limit exceeded (429)")
            if response.status_code == 401:
                self._bearer_token = None  # force re-auth on next attempt
                raise RedditAPIError(f"Reddit returned 401 for r/{sub} (expired token?); forcing re-auth")
            if response.status_code != 200:
                raise RedditAPIError(
                    f"Reddit returned status {response.status_code} for r/{sub}: {response.text[:200]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise RedditAPIError(f"Reddit returned invalid JSON for r/{sub}") from exc

            listing = (payload.get("data") or {}).get("children") or []
            if not isinstance(listing, list):
                logger.warning("Reddit returned unexpected listing shape for r/%s; skipping", sub)
                continue

            for child in listing:
                data = (child or {}).get("data") or {}
                post_id = data.get("id")
                title = data.get("title")
                created_utc = data.get("created_utc")
                if post_id is None or title is None or created_utc is None:
                    continue
                try:
                    created_at = datetime.fromtimestamp(float(created_utc), tz=timezone.utc).replace(tzinfo=None)
                except (TypeError, ValueError, OSError):
                    logger.warning("Discarding Reddit post with unparseable created_utc: %s", created_utc)
                    continue

                if since is not None and created_at < since:
                    continue

                author = data.get("author") or ""
                subreddit = data.get("subreddit") or sub
                permalink = data.get("permalink") or ""
                all_posts.append(
                    RedditPost(
                        post_id=str(post_id),
                        subreddit=str(subreddit),
                        title=str(title),
                        selftext=str(data.get("selftext") or ""),
                        created_at=created_at,
                        author_username=str(author),
                        url=str(data.get("url") or ""),
                        score=int(data.get("score") or 0),
                        num_comments=int(data.get("num_comments") or 0),
                        permalink=f"https://reddit.com{permalink}" if permalink else "",
                    )
                )

        logger.info("Fetched %d Reddit posts across %d subreddits", len(all_posts), len(subreddits))
        return all_posts
