import pytest

from app.intelligence.pricing import TokenUsage, estimate_cost_usd


def test_known_model_uses_its_own_rate():
    cost = estimate_cost_usd("gpt-4o-mini", TokenUsage(prompt_tokens=1000, completion_tokens=1000))
    assert cost == pytest.approx(0.00015 + 0.0006)


def test_zero_tokens_costs_nothing():
    assert estimate_cost_usd("gpt-4o-mini", TokenUsage(0, 0)) == 0.0


def test_unknown_model_falls_back_to_conservative_rate(caplog):
    cost = estimate_cost_usd("some-future-model", TokenUsage(prompt_tokens=1000, completion_tokens=1000))
    # Fallback rate should be at least as expensive as our cheapest known model.
    cheap_cost = estimate_cost_usd("gpt-4o-mini", TokenUsage(1000, 1000))
    assert cost >= cheap_cost


def test_partial_usage_scales_linearly():
    full = estimate_cost_usd("gpt-4o-mini", TokenUsage(2000, 0))
    half = estimate_cost_usd("gpt-4o-mini", TokenUsage(1000, 0))
    assert round(full, 6) == round(half * 2, 6)
