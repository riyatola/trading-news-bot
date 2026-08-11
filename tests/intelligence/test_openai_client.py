import json

import httpx
import pytest

from app.exceptions import OpenAIError
from app.intelligence.openai_client import OpenAIClient

SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"foo": {"type": "string"}},
    "required": ["foo"],
    "additionalProperties": False,
}


def _client_with_response(handler) -> OpenAIClient:
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.AsyncClient(transport=transport)
    return OpenAIClient(api_key="sk-test", model="gpt-4o-mini", client=httpx_client)


@pytest.mark.asyncio
async def test_successful_structured_completion_parses_json_and_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"foo": "bar"})}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7},
            },
        )

    client = _client_with_response(handler)
    result = await client.create_structured_completion("system", "user", SIMPLE_SCHEMA, "test_schema")

    assert result.data == {"foo": "bar"}
    assert result.prompt_tokens == 42
    assert result.completion_tokens == 7


@pytest.mark.asyncio
async def test_missing_api_key_raises_without_network_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    httpx_client = httpx.AsyncClient(transport=transport)
    client = OpenAIClient(api_key="", model="gpt-4o-mini", client=httpx_client)

    with pytest.raises(OpenAIError):
        await client.create_structured_completion("system", "user", SIMPLE_SCHEMA, "test_schema")
    assert calls == []


@pytest.mark.asyncio
async def test_non_200_status_raises_openai_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = _client_with_response(handler)
    with pytest.raises(OpenAIError):
        await client.create_structured_completion("system", "user", SIMPLE_SCHEMA, "test_schema")


@pytest.mark.asyncio
async def test_truncated_response_raises_openai_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = _client_with_response(handler)
    with pytest.raises(OpenAIError):
        await client.create_structured_completion("system", "user", SIMPLE_SCHEMA, "test_schema")


@pytest.mark.asyncio
async def test_non_json_content_raises_openai_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = _client_with_response(handler)
    with pytest.raises(OpenAIError):
        await client.create_structured_completion("system", "user", SIMPLE_SCHEMA, "test_schema")
