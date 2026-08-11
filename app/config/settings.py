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
    news_api_key: str = ""
    sec_user_agent: str = "Market-Intelligence-Bot/1.0"
    
    # X API (Sprint 7)
    x_api_key: str = ""
    x_api_secret: str = ""
    
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


@lru_cache()
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
