"""Tests for app.market.prices.MEXCWebSocketClient message parsing."""
import json

from app.market.prices import MarketTick, MEXCWebSocketClient


def _ticker_push(**overrides):
    data = {
        "symbol": "NVDA_USDT",
        "lastPrice": 450.5,
        "fairPrice": 450.4,
        "indexPrice": 450.3,
        "volume24": 123456.0,
        "holdVol": 7890.0,
        "fundingRate": 0.0001,
        "timestamp": 1_800_000_000_000,
    }
    data.update(overrides)
    return json.dumps({"channel": "push.ticker", "data": data})


def test_parse_message_valid_ticker():
    tick = MEXCWebSocketClient._parse_message(_ticker_push())
    assert isinstance(tick, MarketTick)
    assert tick.symbol == "NVDAUSDT"
    assert tick.price == 450.5
    assert tick.mark_price == 450.4
    assert tick.index_price == 450.3
    assert tick.volume_24h == 123456.0
    assert tick.open_interest == 7890.0
    assert tick.funding_rate == 0.0001


def test_parse_message_ignores_non_ticker_channel():
    msg = json.dumps({"channel": "pong"})
    assert MEXCWebSocketClient._parse_message(msg) is None


def test_parse_message_ignores_non_json():
    assert MEXCWebSocketClient._parse_message("not json") is None


def test_parse_message_missing_symbol_is_discarded():
    msg = json.dumps({"channel": "push.ticker", "data": {"lastPrice": 1.0}})
    assert MEXCWebSocketClient._parse_message(msg) is None


def test_parse_message_missing_price_is_discarded():
    msg = json.dumps({"channel": "push.ticker", "data": {"symbol": "NVDA_USDT"}})
    assert MEXCWebSocketClient._parse_message(msg) is None


def test_parse_message_optional_fields_missing():
    msg = json.dumps({"channel": "push.ticker", "data": {"symbol": "AMD_USDT", "lastPrice": 10.0}})
    tick = MEXCWebSocketClient._parse_message(msg)
    assert tick.symbol == "AMDUSDT"
    assert tick.mark_price is None
    assert tick.index_price is None
    assert tick.volume_24h is None
    assert tick.open_interest is None
    assert tick.funding_rate is None


def test_parse_message_symbol_normalized():
    tick = MEXCWebSocketClient._parse_message(_ticker_push(symbol="amd-usdt"))
    assert tick.symbol == "AMDUSDT"
