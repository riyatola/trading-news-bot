"""LLM token pricing (Sprint 5).

Approximate, hand-maintained USD-per-1K-token rates used only for internal
cost accounting against the daily spend cap (`app.intelligence.cost_tracker`)
-- not billing-accurate to the cent. Update `PRICING_PER_1K_TOKENS` when
switching models or when a provider changes prices; unknown models fall
back to a deliberately conservative (higher) estimate so an unrecognized
model can't silently blow through the cap.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# model -> (input_usd_per_1k_tokens, output_usd_per_1k_tokens)
PRICING_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-4.1": (0.002, 0.008),
}

# Used for any model not in the table above -- intentionally pessimistic
# (roughly gpt-4o's rate) so cost tracking never under-counts an unknown
# or newly-released model.
_FALLBACK_PRICING = (0.0025, 0.01)


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int


def estimate_cost_usd(model: str, usage: TokenUsage) -> float:
    """Estimate the USD cost of one completion call."""
    input_rate, output_rate = PRICING_PER_1K_TOKENS.get(model, _FALLBACK_PRICING)
    if model not in PRICING_PER_1K_TOKENS:
        logger.warning("No pricing entry for model %s; using conservative fallback rate", model)

    cost = (usage.prompt_tokens / 1000) * input_rate + (usage.completion_tokens / 1000) * output_rate
    return round(cost, 6)
