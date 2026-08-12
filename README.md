# Market Intelligence & Trading Signal System

Real-time market intelligence platform that continuously monitors 52 MEXC stock-perpetual assets, integrating multiple data sources (news, SEC filings, company announcements, X, macro data) and uses AI analysis to detect trading opportunities.

## Features

- **Asset Universe**: Automatically maintained 52 MEXC stock perpetuals with sector/industry metadata
- **Market Data**: Real-time price, volume, open interest, and funding rate ingestion from MEXC WebSocket
- **News Intelligence**: Automated ingestion from financial news, SEC EDGAR, and company IR
- **AI Analysis**: Structured event classification, entity extraction, and impact analysis with cost controls
- **Opportunity Scoring**: LONG/SHORT opportunity scores with configurable weights and historical validation
- **Telegram Alerts**: Single-chat alert delivery with clear type labels (🚨BREAKING, 🟢LONG, 🔴SHORT, 🌐MACRO, 📊MARKET, 📋DAILY, 🔎RESEARCH) — all alerts land in one chat prefixed by type so you can scan at a glance
- **Thesis Tracking**: User-created investment theses with supporting/contradicting evidence
- **Graceful Degradation**: Explicit fallback modes when external services fail (no silent failures)

## Architecture

```
Data Sources
    ↓
Ingestion Layer (news, SEC, company IR, MEXC, macro, X)
    ↓
Raw Event Store (immutable)
    ↓
Normalization & Deduplication
    ↓
Entity Extraction & Asset Mapping
    ↓
AI Event Analysis (entity, direction, severity, catalyst, confidence)
    ↓
Market Context (MEXC data + macro data)
    ↓
Opportunity Engine (LONG/SHORT scores, components)
    ↓
Alert Decision
    ↓
Telegram Delivery
```

## Technology Stack

- **Backend**: Python 3.12+, FastAPI
- **Database**: PostgreSQL (Supabase initially)
- **Cache/Queue**: Redis
- **Async Workers**: APScheduler + Redis (→ Celery at scale)
- **AI**: OpenAI API (structured outputs)
- **Market Data**: MEXC REST + WebSocket
- **Delivery**: Telegram Bot API
- **Containerization**: Docker, Docker Compose

## Development Phases (Sprints)

### Sprint 1: Foundation ✓
- FastAPI + PostgreSQL + Redis + Docker
- Database migrations + logging
- System configuration management
- Health check endpoint + basic tests

### Sprint 2: Asset Universe
- 52 MEXC stock perpetuals database + seed from Appendix A
- Asset relationships (manually seeded from 10-K filings)
- MEXC asset synchronization job (hourly)
- Asset endpoints (GET /assets, GET /assets/{ticker})

### Sprint 3: Market Data
- MEXC WebSocket real-time ingestion
- Market snapshots (price, volume, OI, funding)
- Indicator calculations (returns, volatility, momentum)
- Market data endpoints (GET /market/{ticker})

### Sprint 4: News Ingestion
- Financial news API integration
- SEC EDGAR + 10-K ingestion
- Company IR RSS feeds
- Raw event deduplication (event_cluster_id)
- Credibility tier assignment (4-tier static bootstrap)

### Sprint 5: AI Analysis
- Pre-filter gate (cost control before LLM)
- LLM entity extraction (direct, secondary, tertiary)
- Event classification (type, direction, severity, etc.)
- Impact analysis with structured JSON output
- Daily AI spend tracking + cap enforcement

### Sprint 6: Telegram Alerts
- **Single-chat delivery** (recommended): All 7 alert types (BREAKING, LONG, SHORT, MACRO, MARKET, DAILY, RESEARCH) land in ONE Telegram chat/channel, each prefixed with a type label + emoji so you can scan at a glance:
  - 🚨 **BREAKING** — only for CRITICAL-tier LONG/SHORT/MACRO (automatically mirrored from their normal alert)
  - 🟢 **LONG** — bullish opportunities
  - 🔴 **SHORT** — bearish opportunities
  - 🌐 **MACRO** — macro-economic events affecting multiple assets
  - 📊 **MARKET ANOMALY** — price/volume/OI anomalies
  - 📋 **DAILY** — daily briefing (macro regime, top developments, watchlist)
  - 🔎 **RESEARCH** — thesis changes and low-signal research items
- Alert templates with structured fields (score, catalyst, fundamental impact, price reaction, volume, cross-asset effects, confidence, sources)
- Alert decision logic (thresholds: <50 none, 50-65 watch, 65-80 opp, 80-90 high, 90+ critical)
- Daily briefing generation

#### Telegram Setup Instructions

You only need **one bot + one chat/channel** for all 7 alert types — they are differentiated by labels, not by separate chats.

**1. Get TELEGRAM_BOT_TOKEN:**
- Open Telegram, search for `@BotFather`
- Send `/newbot`
- Follow prompts: give your bot a display name, then a unique username ending in `bot` (e.g. `market_intel_alerts_bot`)
- BotFather replies with a token like `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ` — copy this as `TELEGRAM_BOT_TOKEN`

**2. Get TELEGRAM_CHAT_ID (where all alerts get sent):**
- Create a Telegram group or channel (or just plan to message the bot directly for testing)
- Add your bot to that group/channel (make it an admin if you want it to post to a channel)
- Send any message in the group (e.g. "test")
- In a browser, visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
- Look for `"chat":{"id": -1001234567890, ...}` in the JSON response — that number (including the minus sign for groups/channels, or a positive number for a direct bot chat) is your `TELEGRAM_CHAT_ID`

**3. Add to `.env`:**
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=-1001234567890
```

> **Advanced (optional — not required)**: If you later prefer separate chats *or* Telegram Topics within a single supergroup, you can configure `telegram_channel_map` in the `system_config` table with per-channel `{chat_id, message_thread_id}` overrides. See `get_channel_chat_id` in `app/workers/alerts.py` for the resolution logic. Out of the box, nothing needs to be configured beyond the two env vars above.

### Sprint 7: X Integration (After Core Stable)
- X ingestion adapter (Tier-1: company accounts, CEOs, regulators)
- RSS/EDGAR fallback for resilience
- Gradual rollout with monitoring

### Sprint 8: Opportunity Engine
- LONG score calculation (8 configurable components)
- SHORT score calculation
- Historical validation (~30-50 hand-collected events)
- Degraded mode (MEXC unavailable → 'event-only/unconfirmed')
- Opportunity recalculation job (every 15 min)

## Configuration

Create `.env` file from `.env.example`:

```bash
cp .env.example .env
# Edit .env with your credentials
```

### Required Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection URL
- `OPENAI_API_KEY`: OpenAI API key (for structured outputs)
- `OPENAI_MODEL`: Chat completions model used for event analysis (default `gpt-4o-mini`)
- `AI_DAILY_SPEND_CAP_USD`: Hard daily cap on LLM spend (default `100.0`); also editable at runtime via the `system_config` table (key `ai_daily_spend_cap_usd`)
- `MEXC_API_KEY`, `MEXC_API_SECRET`: MEXC market data API (read-only)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: Telegram bot credentials — **only one chat needed.** All 7 alert types (BREAKING/LONG/SHORT/MACRO/MARKET/DAILY/RESEARCH) are delivered to this single chat, each labeled with a type prefix + emoji. See Sprint 6 setup for step-by-step instructions.
- `NEWS_API_KEY`: Financial news API (NewsAPI or equivalent)

### System Configuration

All weights, thresholds, and SLA targets are stored in the `system_config` table (no hard-coding):

- LONG/SHORT score component weights
- Alert thresholds (50-65-80-90 boundaries)
- SLA targets (p50/p95 per source tier)
- AI daily spend cap
- Recalculation intervals
- `telegram_channel_map` (optional advanced): Override per-channel routing to separate chats or Telegram Topics — not needed for the default single-chat setup

## Running the Application

### With Docker Compose (Recommended)

```bash
docker-compose up
```

This starts:
- PostgreSQL database
- Redis cache
- FastAPI application (hot reload in dev mode)

### Manual Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env

# Run migrations
alembic upgrade head

# Start application
uvicorn app.main:app --reload
```

## API Endpoints (Sprint 1+)

### Health & Status
- `GET /health` - Health check (database, Redis, etc.)
- `GET /` - Root endpoint

### Sprint 2: Assets (when ready)
- `GET /assets` - List all assets
- `GET /assets/{ticker}` - Asset details

### Sprint 3: Market Data (when ready)
- `GET /market/{ticker}` - Price, indicators, recent snapshots

### Sprint 4: Events (when ready)
- `GET /events` - List events
- `GET /events/{id}` - Event details

### Sprint 8: Opportunities (when ready)
- `GET /opportunities` - List opportunities
- `GET /opportunities/{id}` - Opportunity details
- `POST /admin/reprocess-event/{id}` - Reprocess event

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/api/test_health.py

# Run with verbose output
pytest -v
```

## Risk Mitigation Strategies

1. **Entity Graph**: Manual seed (10-K edges) + quarterly review; defer auto-discovery to v2
2. **Credibility Scoring**: Static 4-tier bootstrap; dynamic re-scoring only after 90+ days
3. **AI Cost Control**: Pre-filter gate before LLM; daily spend cap with queue fallback
4. **X Fragility**: Mirror Tier-1 via RSS/EDGAR; X as adapter; defer to Sprint 7
5. **Latency SLA**: Explicit p50/p95 targets per source tier in config from Sprint 1
6. **Scoring Validation**: Hand-collected ~30-50 historical events tested retroactively pre-Sprint 8
7. **MEXC Failure**: Explicit 'event-only/unconfirmed' mode, not silent failure

## Database Schema

### Core Tables

- **system_config**: Configurable weights, thresholds, SLA targets, AI costs
- **assets**: 52 MEXC stock perpetuals with metadata
- **asset_relationships**: Competitors, suppliers, customers, sectors, macro links
- **sources**: News, SEC, company IR, X, macro sources with credibility
- **source_accounts**: Individual accounts (CEOs, regulators, analysts)
- **raw_events**: Immutable raw event storage (foundation for auditing)
- **events**: Processed events with AI classification and deduplication
- **event_entities**: Extracted assets with relationship type
- **event_impacts**: Impact analysis and macro connections
- **market_snapshots**: MEXC price/volume/OI/funding with indicators
- **macro_snapshots**: Macro data (rates, inflation, employment, FX, etc.)
- **opportunities**: LONG/SHORT/MACRO scores with components
- **alerts**: Telegram alerts with delivery status
- **ai_spend_log**: Per-call LLM token usage + estimated USD cost, for daily-cap enforcement (Sprint 5)
- **theses**: User-created investment theses
- **thesis_assets**: Assets relevant to theses
- **thesis_evidence**: Supporting/contradicting evidence

## Key Design Principles

1. **Research-First**: Market knowledge graph (events → entities → impact → context → opportunity), not simple sentiment
2. **Immutable Raw Events**: Never delete; foundation for auditing, debugging, reprocessing, prompt improvement
3. **Configurable Everything**: No hard-coded logic; all weights, thresholds, SLA targets in system_config
4. **Graceful Degradation**: Each external dependency has explicit fallback; no silent failures
5. **Cost-Gated AI**: Pre-filter before LLM; daily spend cap; queue overflow for next batch
6. **Latency Tracking**: p50/p95 targets per source tier in config; measured vs. target
7. **Historical Validation**: Formula tested against hand-collected past events before going live
8. **Audit Trail**: Every decision logged with reasoning; full provenance from raw event to alert

## License

MIT

## Author

GitHub Copilot CLI
