"""Prompt construction for Sprint 5's event analysis LLM call."""
from __future__ import annotations

from app.db.models import Asset, RawEvent

SYSTEM_PROMPT = """You are a market-intelligence analyst for a trading signal \
system that monitors a fixed universe of tracked equities. Given one news \
item, SEC filing, or company IR update, classify it and identify which \
tracked assets it affects, directly or indirectly (competitors, suppliers, \
customers, sector peers).

Rules:
- Only use tickers from the provided tracked-asset list for `entities`.
- "direct" relationship = the company named in the story itself.
- "secondary"/"tertiary" = affected indirectly (competitor, supplier, \
customer, sector peer of the named company) -- only include these if the \
effect is plausible and explain why in `impact`.
- Be conservative with `severity` and `confidence`: most routine news is \
low-to-moderate severity (2-5); reserve 8-10 for genuinely major events \
(M&A, regulatory action with material financial impact, guidance shocks).
- `novelty` should be low if the story is a rehash, rumor confirmation, or \
already-priced-in follow-up rather than new information.
- If the event has no clear connection to any tracked asset, still \
classify it but return an empty `entities` list.
"""


def build_user_prompt(raw_event: RawEvent, tracked_assets: list[Asset]) -> str:
    asset_lines = "\n".join(
        f"- {a.ticker}: {a.company_name} ({a.sector} / {a.industry})" for a in tracked_assets
    )
    published = raw_event.published_at.isoformat() if raw_event.published_at else "unknown"
    return (
        f"TRACKED ASSETS:\n{asset_lines}\n\n"
        f"EVENT:\n"
        f"Published: {published}\n"
        f"Title: {raw_event.title}\n"
        f"Content: {raw_event.content}\n"
    )
