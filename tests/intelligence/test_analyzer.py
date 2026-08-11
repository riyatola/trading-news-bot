from datetime import datetime

import pytest

from app.db.models import Asset, RawEvent
from app.exceptions import OpenAIError
from app.intelligence.analyzer import analyze_event
from app.intelligence.openai_client import StructuredCompletionResult


class FakeClient:
    def __init__(self, data: dict, prompt_tokens=100, completion_tokens=50):
        self._data = data
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self.calls = 0

    async def create_structured_completion(self, system_prompt, user_prompt, json_schema, schema_name):
        self.calls += 1
        return StructuredCompletionResult(
            data=self._data,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
        )


def _tracked_assets():
    return [
        Asset(
            id="AST-01", ticker="NVDA", company_name="NVIDIA Corporation",
            mexc_symbol="NVDAUSDT", exchange_ticker="NASDAQ:NVDA",
            sector="Technology", industry="Semiconductors", country="US", currency="USD",
        ),
        Asset(
            id="AST-02", ticker="AMD", company_name="Advanced Micro Devices",
            mexc_symbol="AMDUSDT", exchange_ticker="NASDAQ:AMD",
            sector="Technology", industry="Semiconductors", country="US", currency="USD",
        ),
    ]


def _raw_event():
    return RawEvent(
        id="RAW-1", source_id=1, published_at=datetime.utcnow(),
        title="NVIDIA beats Q3 estimates", content="NVIDIA reported strong data center revenue growth.",
    )


VALID_DATA = {
    "event_type": "earnings",
    "direction": "bullish",
    "severity": 7,
    "confidence": 85,
    "time_horizon": "days",
    "novelty": 60,
    "macro_relevance": 5,
    "catalyst": "Data center beat",
    "reasoning_summary": "Strong data center revenue drove the beat.",
    "impact_summary": "Likely positive reaction; competitors may see sympathy moves.",
    "macro_relevance_detail": None,
    "entities": [
        {"ticker": "NVDA", "relationship": "direct", "direction": "bullish",
         "impact": "Directly beat estimates.", "confidence": 90},
        {"ticker": "AMD", "relationship": "secondary", "direction": "bearish",
         "impact": "Competitive pressure from NVDA's strength.", "confidence": 40},
        {"ticker": "TOTALLY_UNTRACKED", "relationship": "secondary", "direction": "neutral",
         "impact": "Should be dropped.", "confidence": 30},
    ],
}


@pytest.mark.asyncio
async def test_analyze_event_returns_validated_analysis():
    client = FakeClient(VALID_DATA)
    result = await analyze_event(client, _raw_event(), _tracked_assets())

    assert result.analysis.event_type == "earnings"
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50
    assert client.calls == 1


@pytest.mark.asyncio
async def test_analyze_event_drops_untracked_tickers():
    client = FakeClient(VALID_DATA)
    result = await analyze_event(client, _raw_event(), _tracked_assets())

    tickers = {e.ticker for e in result.analysis.entities}
    assert tickers == {"NVDA", "AMD"}


@pytest.mark.asyncio
async def test_analyze_event_raises_openai_error_on_invalid_schema():
    bad_data = dict(VALID_DATA)
    bad_data["severity"] = 999  # out of range -> pydantic ValidationError
    client = FakeClient(bad_data)

    with pytest.raises(OpenAIError):
        await analyze_event(client, _raw_event(), _tracked_assets())
