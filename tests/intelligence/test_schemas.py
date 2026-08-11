import pytest
from pydantic import ValidationError

from app.intelligence.schemas import EventAnalysis


VALID_PAYLOAD = {
    "event_type": "earnings",
    "direction": "bullish",
    "severity": 6,
    "confidence": 80,
    "time_horizon": "days",
    "novelty": 70,
    "macro_relevance": 10,
    "catalyst": "Q3 earnings beat",
    "reasoning_summary": "Company beat EPS and revenue estimates with raised guidance.",
    "impact_summary": "Expect a positive short-term price reaction on the beat and raise.",
    "macro_relevance_detail": None,
    "entities": [
        {
            "ticker": "NVDA",
            "relationship": "direct",
            "direction": "bullish",
            "impact": "Directly named beneficiary of the earnings beat.",
            "confidence": 90,
        }
    ],
}


def test_valid_payload_parses():
    analysis = EventAnalysis.model_validate(VALID_PAYLOAD)
    assert analysis.event_type == "earnings"
    assert analysis.entities[0].ticker == "NVDA"


def test_severity_out_of_range_rejected():
    bad = dict(VALID_PAYLOAD, severity=11)
    with pytest.raises(ValidationError):
        EventAnalysis.model_validate(bad)


def test_invalid_event_type_rejected():
    bad = dict(VALID_PAYLOAD, event_type="not_a_real_type")
    with pytest.raises(ValidationError):
        EventAnalysis.model_validate(bad)


def test_empty_entities_allowed():
    payload = dict(VALID_PAYLOAD, entities=[])
    analysis = EventAnalysis.model_validate(payload)
    assert analysis.entities == []


def test_json_schema_is_strict():
    schema = EventAnalysis.json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())
    # Nested $defs (EntityImpact) must also be strict.
    entity_schema = schema["$defs"]["EntityImpact"]
    assert entity_schema["additionalProperties"] is False
    assert set(entity_schema["required"]) == set(entity_schema["properties"].keys())
