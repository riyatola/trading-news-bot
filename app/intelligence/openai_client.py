"""OpenAI chat-completions client (Sprint 5).

Thin REST wrapper, mirroring the error-handling shape of
`app.market.mexc.MEXCClient` / `app.ingestion.news.newsapi_client.NewsAPIClient`:
network/shape failures raise `OpenAIError` so callers can apply consistent
handling. Uses the Chat Completions API's structured-outputs
(`response_format: json_schema`, strict mode) so the response is
guaranteed to match the schema `app.intelligence.schemas.EventAnalysis`
defines -- no free-text parsing/regex needed on our side.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.exceptions import OpenAIError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class StructuredCompletionResult:
    data: dict
    prompt_tokens: int
    completion_tokens: int


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client  # injectable for testing

    async def create_structured_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
        schema_name: str,
    ) -> StructuredCompletionResult:
        """Call chat/completions with a strict JSON-schema response format.

        Raises:
            OpenAIError: on missing API key, network failure, non-200
                response, or a response that doesn't contain valid JSON
                matching the requested shape.
        """
        if not self._api_key:
            raise OpenAIError("OpenAI request skipped: no API key configured")

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            if self._client is not None:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=self._timeout,
                    )
        except httpx.HTTPError as exc:
            raise OpenAIError(f"OpenAI request failed: {exc}") from exc

        if response.status_code != 200:
            raise OpenAIError(
                f"OpenAI returned status {response.status_code}: {response.text[:300]}"
            )

        try:
            payload_out = response.json()
        except ValueError as exc:
            raise OpenAIError("OpenAI returned invalid JSON") from exc

        try:
            choice = payload_out["choices"][0]
            content = choice["message"]["content"]
            usage = payload_out.get("usage") or {}
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIError(f"OpenAI response missing expected fields: {exc}") from exc

        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise OpenAIError("OpenAI response truncated (finish_reason=length)")

        try:
            data = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise OpenAIError(f"OpenAI response content was not valid JSON: {exc}") from exc

        return StructuredCompletionResult(
            data=data,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )
