# Sprint 5: AI Analysis Engine — Implementation Notes

## What this sprint adds

A worker (`app/workers/event_processing.py`, polled every 5 minutes by
`app.workers.scheduler`) that drains the backlog of unclassified `events`
rows created by Sprint 4's dedup step and fills in:

- `events`: `event_type`, `direction`, `severity`, `confidence`,
  `time_horizon`, `novelty`, `macro_relevance`, `catalyst`,
  `reasoning_summary`
- `event_entities`: one row per tracked asset the event affects (direct,
  secondary, or tertiary), with a per-asset direction/impact/confidence
- `event_impacts`: an overall impact summary + macro/cross-asset detail

## Design decisions worth knowing about

**One LLM call, not three.** The plan lists entity extraction,
classification, and impact analysis as separate line items, but they all
require the same read of the same event text, so `app/intelligence/schemas.py`'s
`EventAnalysis` produces everything in a single structured-output call
(`app/intelligence/analyzer.py`). Three calls would triple token spend
against the same daily cap for no accuracy benefit.

**Pre-filter gate (`app/intelligence/prefilter.py`)** runs before any LLM
call and has two independent savings:
1. Skip events whose raw content is too short to classify reliably
   (`system_config` key `prefilter_min_content_length`, default 40 chars).
2. Reuse an already-classified sibling event's full analysis (copying
   `event_entities`/`event_impacts` too) when it shares Sprint 4's
   `event_cluster_id` — the same story reported by three wire services
   only costs one LLM call.

**Daily spend cap, "queue fallback" behavior.** `app/intelligence/cost_tracker.py`
sums `ai_spend_log.cost_usd` for the current UTC day against
`system_config` key `ai_daily_spend_cap_usd` (falls back to
`Settings.ai_daily_spend_cap_usd`, default $100/day). Once exceeded, the
worker stops calling the LLM for the rest of the batch and leaves those
events with `processed_at IS NULL` — they're picked up automatically on
the next poll once the next UTC day's spend resets, rather than being
dropped or erroring. A non-positive cap fails closed (treated as
"exceeded") rather than "unlimited."

**Custom httpx client, not the `openai` package.** `app/intelligence/openai_client.py`
mirrors the existing `MEXCClient` / `NewsAPIClient` / `SECEDGARClient`
pattern already in the codebase (injectable `httpx.AsyncClient` for
testing, raises a single custom exception — `OpenAIError`, already
defined in `app/exceptions.py`). No new runtime dependency. Uses the Chat
Completions API's strict JSON-schema structured outputs so responses are
guaranteed to match `EventAnalysis`'s shape; Pydantic validation on the
way back out is a second, defense-in-depth check.

**Failure handling** mirrors `app.workers.news_ingestion`: one event's
LLM call failing (network error, schema validation failure) is logged and
leaves that event `processed_at IS NULL` for retry next cycle — it
doesn't stop the rest of the batch.

## New/changed files

- `app/intelligence/` (new package): `schemas.py`, `prompts.py`,
  `openai_client.py`, `analyzer.py`, `prefilter.py`, `cost_tracker.py`,
  `pricing.py`
- `app/config/system_config.py` (new): typed `system_config` get/set with
  in-code defaults, so the cap/thresholds are DB-editable
- `app/workers/event_processing.py` (new): the poll worker
- `app/workers/scheduler.py`: registers `event_processing_poll`
  (5-minute interval) and its job wrapper
- `app/db/models.py`: new `AISpendLog` model
- `app/config/settings.py`: `openai_model`, `openai_base_url`,
  `openai_timeout_seconds`, `event_processing_batch_size`
- `migrations/versions/002_ai_spend_log.py`
- `scripts/seed_system_config.py`: seeds the Sprint 5 `system_config`
  defaults so they show up as editable rows
- `tests/intelligence/`, `tests/workers/test_event_processing.py`

## Running it

```bash
# after alembic upgrade head (or Base.metadata.create_all in dev):
python -m scripts.seed_system_config   # optional, makes cap/threshold DB-editable

# set in .env:
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini   # default
AI_DAILY_SPEND_CAP_USD=100.0

pytest tests/intelligence tests/workers/test_event_processing.py -v
```

The scheduler picks up `event_processing_poll` automatically at app
startup (see `app.main.startup_event` → `app.workers.scheduler.start_scheduler`),
same as the existing asset-sync and news-ingestion jobs.

## Known gaps / natural follow-ups

- No `POST /admin/reprocess-event/{id}` endpoint yet (listed in the
  overall plan under Sprint 8) — `Event.is_reprocessable` is set but
  nothing currently flips `processed_at` back to `NULL` on demand.
- Pricing table in `app/intelligence/pricing.py` is hand-maintained and
  approximate, not billing-accurate — fine for cap enforcement, not for
  finance reporting.
- Pre-filter is intentionally simple (length + cluster reuse only); a
  smarter rule-based relevance filter (e.g. keyword/ticker matching
  against title before even queuing for LLM) is a reasonable v2 addition
  if NewsAPI's OR-query batching produces too many false positives in
  practice.
