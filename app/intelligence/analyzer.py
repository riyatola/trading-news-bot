"""Event analysis orchestration (Sprint 5).

Ties together prompt construction, the LLM call, and response validation.
Kept separate from `app.workers.event_processing` so it can be unit
tested against a fake/mocked `OpenAIClient` without a DB, mirroring the
`load_history`/`persist_tick` split in `app.workers.market_ingestion`.
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from app.db.models import Asset, RawEvent
from app.exceptions import OpenAIError
from app.intelligence.openai_client import OpenAIClient
from app.intelligence.prompts import SYSTEM_PROMPT, build_user_prompt
from app.intelligence.schemas import EventAnalysis

logger = logging.getLogger(__name__)

SCHEMA_NAME = "event_analysis"


class AnalysisResult:
    __slots__ = ("analysis", "prompt_tokens", "completion_tokens")

    def __init__(self, analysis: EventAnalysis, prompt_tokens: int, completion_tokens: int):
        self.analysis = analysis
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


async def analyze_event(
    client: OpenAIClient, raw_event: RawEvent, tracked_assets: list[Asset]
) -> AnalysisResult:
    """Classify `raw_event` and extract affected tracked assets.

    Raises:
        OpenAIError: on any LLM call failure, or if the model's response
            doesn't validate against `EventAnalysis` (treated the same as
            a call failure -- the caller's retry/dead-letter handling
            applies uniformly).
    """
    user_prompt = build_user_prompt(raw_event, tracked_assets)
    result = await client.create_structured_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        json_schema=EventAnalysis.json_schema(),
        schema_name=SCHEMA_NAME,
    )

    try:
        analysis = EventAnalysis.model_validate(result.data)
    except ValidationError as exc:
        raise OpenAIError(f"OpenAI response failed schema validation: {exc}") from exc

    tracked_tickers = {a.ticker for a in tracked_assets}
    unknown = [e.ticker for e in analysis.entities if e.ticker not in tracked_tickers]
    if unknown:
        logger.warning(
            "Analyzer returned %d entities outside the tracked universe (dropped): %s",
            len(unknown), unknown,
        )
        analysis = analysis.model_copy(
            update={"entities": [e for e in analysis.entities if e.ticker in tracked_tickers]}
        )

    return AnalysisResult(
        analysis=analysis,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
