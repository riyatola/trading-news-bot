"""Telegram Bot API delivery client (Sprint 6).

Thin REST wrapper, mirroring the error-handling shape of
`app.market.mexc.MEXCClient` / `app.intelligence.openai_client.OpenAIClient`:
network/shape failures raise `TelegramError` so callers
(`app.workers.alerts`, `app.workers.briefing`) can apply consistent
retry/dead-letter handling instead of crashing the worker.

Multi-channel delivery (BREAKING/LONG/SHORT/MACRO/MARKET/DAILY/RESEARCH)
is resolved one level up (see `app.workers.alerts.get_channel_chat_id`) --
this client only knows how to send one message to one chat_id (optionally
scoped to a Telegram "topic" via `message_thread_id`, for operators who
run all channels as topics within a single supergroup rather than as
separate bot chats).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.exceptions import TelegramError

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 15.0

# Telegram's hard per-message character limit (sendMessage 400s above this).
MAX_MESSAGE_LENGTH = 4096


@dataclass(frozen=True)
class TelegramSendResult:
    message_id: str
    chat_id: str


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        base_url: str = TELEGRAM_API_BASE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._bot_token = bot_token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client  # injectable for testing

    async def send_message(
        self,
        chat_id: str,
        text: str,
        message_thread_id: Optional[int] = None,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
    ) -> TelegramSendResult:
        """Send one message.

        Raises:
            TelegramError: on missing bot token/chat_id, network failure,
                or a non-ok Telegram API response.
        """
        if not self._bot_token:
            raise TelegramError("Telegram send skipped: no bot token configured")
        if not chat_id:
            raise TelegramError("Telegram send skipped: no chat_id configured")

        if len(text) > MAX_MESSAGE_LENGTH:
            # Truncate rather than fail outright -- a slightly-truncated
            # alert arriving is better than a delivery failure for what
            # is usually just an over-long cross-asset-effects list.
            logger.warning("Telegram message exceeds %d chars; truncating", MAX_MESSAGE_LENGTH)
            text = text[: MAX_MESSAGE_LENGTH - 20].rstrip() + "\n\n[truncated]"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id

        url = f"{self._base_url}/bot{self._bot_token}/sendMessage"

        try:
            if self._client is not None:
                response = await self._client.post(url, json=payload, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=payload, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram request failed: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramError("Telegram returned invalid JSON") from exc

        if response.status_code != 200 or not body.get("ok"):
            raise TelegramError(
                f"Telegram sendMessage failed (status {response.status_code}): "
                f"{body.get('description', response.text[:200])}"
            )

        result = body.get("result") or {}
        chat = result.get("chat") or {}
        return TelegramSendResult(
            message_id=str(result.get("message_id", "")),
            chat_id=str(chat.get("id", chat_id)),
        )
