"""Structured-output schema for Sprint 5's LLM event analysis call.

One LLM call produces everything needed for `events` (classification),
`event_entities` (extracted assets), and `event_impacts` (impact summary +
macro/cross-asset effects) -- combining what the plan lists as three
separate concerns into a single structured completion, since they all
depend on the same read of the raw event text and splitting them into
three calls would triple the token spend against the same daily cap for
no accuracy benefit.

`EventAnalysis.json_schema()` is passed to the OpenAI structured-outputs
API (`app.intelligence.openai_client`) so the model's response is
guaranteed to match this shape; `pydantic` validation on the way back out
is a second, defense-in-depth check (a provider bug or schema drift
shouldn't silently corrupt `events`/`event_entities` rows).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

EventType = Literal[
    "earnings", "guidance", "regulation", "m_and_a", "product_launch",
    "leadership_change", "litigation", "macro", "partnership",
    "supply_chain", "analyst_rating", "other",
]
Direction = Literal["bullish", "bearish", "neutral", "mixed"]
TimeHorizon = Literal["intraday", "days", "weeks", "months"]
EntityRelationship = Literal["direct", "secondary", "tertiary"]


class EntityImpact(BaseModel):
    """One asset affected by the event -- direct (named in the story) or
    indirect (via `app.db.models.AssetRelationship`, e.g. a competitor or
    supplier of the directly-affected company)."""

    ticker: str = Field(description="Tracked asset ticker, e.g. 'NVDA'.")
    relationship: EntityRelationship = Field(
        description="'direct' if named in the event; 'secondary'/'tertiary' "
        "if affected via a competitor/supplier/sector relationship."
    )
    direction: Direction
    impact: str = Field(description="One-sentence explanation of the impact on this asset.")
    confidence: int = Field(ge=0, le=100)


class EventAnalysis(BaseModel):
    event_type: EventType
    direction: Direction
    severity: int = Field(ge=1, le=10, description="1=minor, 10=major market-moving event.")
    confidence: int = Field(ge=0, le=100, description="Model's confidence in this classification.")
    time_horizon: TimeHorizon
    novelty: int = Field(ge=0, le=100, description="0=old news/already priced in, 100=genuinely new.")
    macro_relevance: int = Field(ge=0, le=100, description="0=no macro connection, 100=primarily macro-driven.")
    catalyst: str = Field(description="Short (<10 word) catalyst label, e.g. 'Q3 earnings beat'.")
    reasoning_summary: str = Field(description="2-4 sentence explanation of the classification.")
    impact_summary: str = Field(description="2-3 sentence summary of the event's expected market impact.")
    macro_relevance_detail: Optional[str] = Field(
        default=None, description="Which macro variable(s) this connects to, if any (e.g. 'oil prices', 'Fed rate path')."
    )
    entities: list[EntityImpact] = Field(default_factory=list, max_length=15)

    @classmethod
    def json_schema(cls) -> dict:
        """OpenAI structured-outputs-compatible JSON schema (strict mode:
        every property required, no additionalProperties)."""
        schema = cls.model_json_schema()
        return _make_strict(schema)


def _make_strict(schema: dict) -> dict:
    """Recursively enforce OpenAI's strict-structured-output constraints:
    every object requires all its properties and disallows extras."""
    if schema.get("type") == "object" and "properties" in schema:
        schema["required"] = list(schema["properties"].keys())
        schema["additionalProperties"] = False
        for value in schema["properties"].values():
            _make_strict(value)
    if schema.get("type") == "array" and "items" in schema:
        _make_strict(schema["items"])
    for key in ("$defs", "definitions"):
        if key in schema:
            for value in schema[key].values():
                _make_strict(value)
    return schema
