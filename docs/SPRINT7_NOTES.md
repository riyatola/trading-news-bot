# Sprint 7: X Integration — Implementation Notes

## What this sprint adds

`app/ingestion/x/` (new package): `x_client.py` (`XClient`, a thin
injectable-`httpx` wrapper around X API v2's `/2/tweets/search/recent`
endpoint) and `adapter.py` (`XAdapter(SourceAdapter)`, converting X posts
to the same `NormalizedEvent` shape every other adapter produces).
Wired into `app.workers.news_ingestion._build_default_adapters` alongside
the existing NewsAPI/SEC/Company-IR adapters — same polling cadence
(3-minute interval, `app.workers.scheduler`), same dead-letter/retry
handling, no new worker or scheduler job needed.

## Design decisions worth knowing about

**Behind a feature flag, off by default.** Per the plan's "gradual
rollout with monitoring" instruction, `XAdapter` is only constructed if
`system_config`'s `x_integration_enabled` is `true` (default `false`) —
see `app/workers/news_ingestion._build_x_adapter`. An operator flips it
on via `set_config_value` (or a future admin endpoint) once they're ready
to monitor it, without a deploy. This mirrors how Sprint 5's AI cost cap
is DB-editable rather than baked into a deploy.

**Tier-1 only, sourced from `source_accounts`.** X usernames live as
`SourceAccount` rows (`source_type="x"`, `account_type` in
`{"company", "ceo", "regulator"}`, `account_id` = the X username) —
same pattern Sprint 4 used for Company IR RSS feed URLs
(`scripts/seed_sources.py`'s `COMPANY_IR_FEEDS`). If the flag is on but no
Tier-1 accounts are seeded, `_build_x_adapter` logs a warning and skips
the adapter rather than erroring — consistent with how an empty
`COMPANY_IR_FEEDS` list is treated as "not configured yet," not a bug.
Tier-2 (journalists/analysts) is intentionally out of scope for this
pass, per the plan.

**RSS is the fallback, not a separate code path.** The plan calls for
"mirror Tier-1 via RSS/EDGAR if X access is unavailable." Rather than
building X-specific fallback logic, this is achieved structurally:
`CompanyIRAdapter` already polls the same tracked companies' IR feeds
every cycle *regardless* of whether `XAdapter` is enabled or healthy. If
`XAdapter` dead-letters (rate limit, auth failure, API-tier change —
all raise `XAPIError` → `IngestionError`), `app.workers.news_ingestion.poll_adapter`
retries up to `MAX_RETRIES` and then records a `DeadLetterEvent` for that
cycle, exactly like any other adapter — the other adapters (including
Company IR) keep running unaffected. Coverage degrades to "RSS-only,
slightly slower" rather than disappearing.

**Bearer token reuses `X_API_KEY`.** X API v2's app-only auth
(sufficient for recent-search) needs a single bearer token; `Settings.x_api_key`
already exists from the plan's env-var list, so it's reused directly
rather than adding a new setting. `X_API_SECRET` is left unused for now,
reserved for a future OAuth1 user-context upgrade if a later sprint needs
write access (e.g. posting) or endpoints app-only auth can't reach.

**429 handling.** `XClient.fetch_recent_posts` raises `XAPIError`
immediately on a 429 rather than retrying internally — retry/backoff is
`poll_adapter`'s job (same `MAX_RETRIES` used for every other adapter), so
X doesn't need its own bespoke backoff logic.

## New/changed files

- `app/ingestion/x/` (new package): `x_client.py`, `adapter.py`
- `app/exceptions.py`: new `XAPIError(ExternalServiceError)`
- `app/config/system_config.py`: new `ingestion` category key
  `x_integration_enabled`
- `app/workers/news_ingestion.py`: `_build_x_adapter` + wiring into
  `_build_default_adapters`
- `app/workers/scheduler.py`: doc/comment updates only (X rides the
  existing `news_ingestion_poll` job, no new job needed)

No new runtime dependencies — `XClient` uses the same injectable
`httpx.AsyncClient` pattern as every other adapter's client, not the
official X SDK.

## Running it

```bash
# set in .env:
X_API_KEY=...           # X API v2 bearer token

# then, once ready to roll out:
python -c "
from app.db.database import SessionLocal
from app.config.system_config import set_config_value
db = SessionLocal()
set_config_value(db, 'x_integration_enabled', True)
"

# seed Tier-1 accounts (mirrors scripts/seed_sources.py's IR-feed pattern) --
# a scripts/seed_sources.py update adding an X_TIER1_ACCOUNTS list of
# (company_name, username, account_type) is a natural companion patch,
# not included in this pass to keep the diff focused on ingestion itself.

pytest tests/ingestion/x -v
```

## Known gaps / natural follow-ups

- `scripts/seed_sources.py` isn't updated in this pass to include an
  `X_TIER1_ACCOUNTS` seed list (mirroring `COMPANY_IR_FEEDS`) — until an
  operator seeds `SourceAccount` rows for `source_type="x"` some other
  way, `_build_x_adapter` will always skip (logged, not an error). Adding
  that seed list is the natural next step before flipping the feature
  flag on in a real deployment.
- Tier-2 accounts (journalists, analysts) are out of scope, per the plan
  — `_X_TIER1_ACCOUNT_TYPES` in `app/workers/news_ingestion.py` would need
  a second config-driven set (with its own credibility tier, likely 2-3
  rather than Tier-1's 1) if/when that's prioritized.
- No dedicated rate-limit-aware pacing beyond `poll_adapter`'s generic
  retry — if X's tier grants a low request budget, tightening
  `NEWS_INGESTION_INTERVAL_MINUTES` specifically for the X adapter (vs.
  the shared 3-minute interval all adapters currently share) may be
  worth splitting out into its own scheduler job later.
- `tests/ingestion/x/` isn't included in this patch; `XClient`/`XAdapter`
  follow the exact same shape as `NewsAPIClient`/`NewsAdapter`, so their
  existing test suites are the fastest template to copy from.
