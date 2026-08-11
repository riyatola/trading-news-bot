"""Tests for app.market.mexc.MEXCClient."""
import httpx
import pytest

from app.exceptions import MEXCAPIError
from app.market.mexc import MEXCClient


def _client_with_transport(transport: httpx.MockTransport) -> MEXCClient:
    async_client = httpx.AsyncClient(transport=transport)
    return MEXCClient(client=async_client)


@pytest.mark.asyncio
async def test_fetch_instruments_success():
    payload = {
        "success": True,
        "data": [
            {"symbol": "NVDA_USDT", "displayName": "NVDA", "state": 0},
            {"symbol": "AMD_USDT", "displayName": "AMD", "state": 0},
            {"symbol": "XOM_USDT", "displayName": "XOM", "state": 1},  # disabled
        ],
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _client_with_transport(httpx.MockTransport(handler))
    instruments = await client.fetch_instruments()

    assert len(instruments) == 3
    active_symbols = {i.symbol for i in instruments if i.is_active}
    assert active_symbols == {"NVDA_USDT", "AMD_USDT"}


@pytest.mark.asyncio
async def test_fetch_instruments_non_200_raises():
    def handler(request):
        return httpx.Response(500, text="server error")

    client = _client_with_transport(httpx.MockTransport(handler))
    with pytest.raises(MEXCAPIError):
        await client.fetch_instruments()


@pytest.mark.asyncio
async def test_fetch_instruments_bad_json_raises():
    def handler(request):
        return httpx.Response(200, text="not json")

    client = _client_with_transport(httpx.MockTransport(handler))
    with pytest.raises(MEXCAPIError):
        await client.fetch_instruments()


@pytest.mark.asyncio
async def test_fetch_instruments_missing_data_field_raises():
    def handler(request):
        return httpx.Response(200, json={"success": True})

    client = _client_with_transport(httpx.MockTransport(handler))
    with pytest.raises(MEXCAPIError):
        await client.fetch_instruments()


@pytest.mark.asyncio
async def test_fetch_instruments_network_error_raises():
    def handler(request):
        raise httpx.ConnectError("connection failed", request=request)

    client = _client_with_transport(httpx.MockTransport(handler))
    with pytest.raises(MEXCAPIError):
        await client.fetch_instruments()


def test_normalize_symbol():
    assert MEXCClient.normalize_symbol("NVDA_USDT") == "NVDAUSDT"
    assert MEXCClient.normalize_symbol("nvda-usdt") == "NVDAUSDT"
    assert MEXCClient.normalize_symbol("NVDAUSDT") == "NVDAUSDT"
