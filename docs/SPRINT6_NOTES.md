# Sprint 6: Telegram Alerts — Implementation Notes

## What this sprint adds

Two workers, polled/scheduled by `app.workers.scheduler`:

- `app/workers/alerts.py` (every 1 minute) drains `opportunities` rows
  that don't yet have a *sent* `Alert`, decides whether/where to alert
  (`app/scoring/alert_decision.py`), renders the channel-appropriate
  template (`app/notifications/templates.py`), and delivers it via
  `app/notifications/telegram.py`.
- `app/workers/briefing.py` (daily cron, 13:00 UTC) summarizes the last
  24h of opportunities + the latest macro snapshot into one DAILY-channel
  message.

Both depend on the `opportunities` table already defined in
`app/db/models.py` (Sprint 8 is what actually *populates* long/short/macro
scores) — this sprint only consumes whatever `Opportunity` rows exist,
so it's independently testable/runnable ahead of Sprint 8 landing.

## Design decisions worth knowing about

**Thresholds live in `system_config`, not code.** `alert_threshold_watchlist`
/ `_opportunity` / `_high_priority` / `_critical` default to the README's
50/65/80/90 boundaries but are DB-editable (`app/scoring/alert_decision.py`),
consistent with the project's "configurable everything" principle. A
non-positive/misconfigured cap doesn't apply here (unlike Sprint 5's spend
cap) — thresholds just gate which tier an opportunity lands in.

**One `Alert` row per (opportunity, channel).** A CRITICAL-tier LONG/SHORT
/MACRO opportunity is delivered to its normal channel *and* mirrored to
BREAKING — two separate `Alert` rows, since BREAKING exists specifically
to surface the most urgent items regardless of underlying type. Idempotency
is per-channel: re-running the dispatch loop won't double-send a channel
that already has `status="sent"`.

**Retry, not drop, on delivery failure.** Mirrors the "no silent failures"
pattern from Sprints 4-5: a `TelegramError` (network issue, bad chat_id,
Telegram-side 4xx/5xx) increments `Alert.delivery_attempts` and sets
`status="retrying"` (or `"failed"` after `MAX_DELIVERY_ATTEMPTS = 3`); the
next poll cycle picks it back up. Opportunities that never crossed the
watchlist threshold don't get an `Alert` row at all, so a later
opportunity-recalculation pass (Sprint 8) that raises the score is picked
up naturally without extra bookkeeping.

**Multi-channel routing via `system_config`, not hard-coded chat IDs.**
`telegram_channel_map` (`{channel: {chat_id, message_thread_id}}`) lets an
operator either run each channel as a separate bot chat, or as topics
within one supergroup (`message_thread_id`). A fresh install with only
`TELEGRAM_CHAT_ID` set falls back to sending every channel there with no
topic — works out of the box, upgradeable without a deploy.

**Templates are pure functions.** `app/notifications/templates.py` takes
already-loaded ORM rows and returns Markdown text — no DB/network access —
mirroring `app.intelligence.prompts.build_user_prompt`'s separation of
"build the text" from "do the I/O" (`app.workers.alerts` does the
loading/sending). Makes them trivial to unit test without a DB or a live
bot token.

## New/changed files

- `app/notifications/` (new package): `telegram.py`, `templates.py`
- `app/scoring/alert_decision.py` (new)
- `app/workers/alerts.py`, `app/workers/briefing.py` (new)
- `app/config/system_config.py`: new `alerts` category keys
  (`alert_threshold_*`, `telegram_channel_map`)
- `app/workers/scheduler.py`: registers `alert_dispatch_poll` (1-minute
  interval) and `daily_briefing` (13:00 UTC cron)

No new runtime dependencies — Telegram delivery uses the same injectable
`httpx.AsyncClient` pattern as `MEXCClient`/`OpenAIClient`, not a Telegram
SDK.

## Running it

```bash
# after alembic upgrade head (or Base.metadata.create_all in dev):
python -m scripts.seed_system_config   # seeds the new alert_threshold_* / telegram_channel_map defaults

# set in .env:
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

pytest tests/notifications tests/scoring/test_alert_decision.py tests/workers/test_alerts.py tests/workers/test_briefing.py -v
```

The scheduler picks up both new jobs automatically at app startup (see
`app.main.startup_event` → `app.workers.scheduler.start_scheduler`), same
as the existing asset-sync/news-ingestion/event-processing jobs.

## Known gaps / natural follow-ups

- No opportunities exist yet in a fresh deployment until Sprint 8's
  scoring engine runs — `app/workers/alerts.py` and `app/workers/briefing.py`
  are fully functional against the `opportunities` table's schema but will
  simply have nothing to dispatch/summarize until then. Recommend seeding
  a handful of hand-built `Opportunity` rows for manual QA of alert
  formatting/delivery ahead of Sprint 8 landing.
- Telegram's ~1 message/second-per-chat soft rate limit isn't explicitly
  paced by `app/workers/alerts.py` — fine at expected v1 alert volumes
  (a handful per poll cycle), but worth adding an explicit send queue with
  backoff if BREAKING-channel volume grows.
- `app/notifications/templates.py` and `app/scoring/alert_decision.py`
  don't yet have a `tests/` directory in this patch — both are pure
  functions and straightforward to test with fixture ORM objects; adding
  coverage here is a good first follow-up.
- Alert delivery `status` values (`pending`/`sent`/`failed`/`retrying`)
  match `Alert.status`'s existing column comment in `app/db/models.py`,
  but there's no admin endpoint yet to manually re-trigger a `"failed"`
  alert — a natural pairing with Sprint 8's planned
  `POST /admin/reprocess-event/{id}`.
