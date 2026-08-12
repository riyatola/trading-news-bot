"""Application settings and configuration management."""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    database_url: str = "sqlite:///./market_intelligence.db"
    redis_url: str = "redis://localhost:6379"
    
    # API Keys
    openai_api_key: str = ""
    # Sprint 5: AI analysis engine. gpt-4o-mini is the default -- cheap
    # enough to run per-event within the daily spend cap while still
    # supporting structured (JSON schema) outputs. Override per-deployment
    # via env var if a different model/quality tradeoff is needed.
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 30.0
    # How many pending (unprocessed) events the event-processing worker
    # pulls per poll cycle. Kept modest so a single slow cycle doesn't
    # starve the scheduler's other jobs; the 5-minute interval (see
    # app.workers.scheduler) will pick up any remainder next cycle.
    event_processing_batch_size: int = 25
    mexc_api_key: str = ""
    mexc_api_secret: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Sprint 4: financial news ingestion. Finnhub's company-news endpoint
    # is ticker-scoped (see app.ingestion.news.finnhub_client), replacing
    # an earlier NewsAPI-backed integration that used free-text company
    # name queries.
    finnhub_api_key: str = ""
    sec_user_agent: str = "Market-Intelligence-Bot/1.0"
    
    # X API (Sprint 7) — DEPRECATED. Replaced by the 3 alternatives below
    # (Finnhub Social Sentiment + ApeWisdom + Reddit + Quiver). X's API is
    # expensive/fragile; the alternatives cover finance social + retail
    # sentiment + regulatory signals better for free/cheap. Left in place
    # only if you explicitly want to re-enable it (not recommended).
    x_api_key: str = ""
    x_api_secret: str = ""

    # Sprint 7: social + alternative-signal integrations (replacing X).
    # Aug-2026 reality: StockTwits closed NEW signups (api.stocktwits.com/
    # developers); Quiver is paid-only now (~$30/mo). Best free sources:
    #   - Finnhub Social Sentiment: free on your existing FINNHUB_API_KEY
    #     plan (1 extra req/ticker per poll, 60 req/min free pool)
    #   - ApeWisdom WSB: FREE, no signup, no API key needed
    #   - Reddit OAuth: free 60 req/min (script app)
    stocktwits_access_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "MarketIntelBot/0.1"
    quiver_quant_api_key: str = ""
    
    # Application
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    
    # SLA Targets (milliseconds)
    sla_p50_breaking: int = 3000
    sla_p95_breaking: int = 180000
    sla_p50_news: int = 5000
    sla_p95_news: int = 600000
    
    # AI Cost Controls
    ai_daily_spend_cap_usd: float = 100.0
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
