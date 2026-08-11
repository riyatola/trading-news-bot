"""Main FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import get_settings
from app.config.logging_config import configure_logging
from app.db.database import engine
from app.db.models import Base
from app.api import health, assets, market
from app.workers.scheduler import start_scheduler, shutdown_scheduler
from app.workers.market_ingestion import start_market_ingestion, stop_market_ingestion
from app.workers.news_ingestion import start_news_ingestion
import logging

# Configure logging
logger_instance = configure_logging()
logger = logging.getLogger(__name__)

# Initialize settings
settings = get_settings()

# Create database tables. In real deployments docker-compose's healthcheck
# guarantees Postgres is up before the app container starts. When the app
# module is imported without a reachable database (e.g. unit tests, which
# use their own isolated SQLite engine via dependency overrides), we log and
# continue instead of crashing at import time -- this is not a request-path
# failure, so it doesn't need the full graceful-degradation machinery used
# for external services at runtime.
try:
    Base.metadata.create_all(bind=engine)
except Exception as exc:  # noqa: BLE001
    logging.getLogger(__name__).warning(
        "Skipping create_all at startup: database unreachable (%s). "
        "This is expected in test environments with an isolated test DB.",
        exc,
    )

# Initialize FastAPI app
app = FastAPI(
    title="Market Intelligence Trading Signal System",
    description="Real-time market intelligence platform for 52 MEXC stock-perpetual assets",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(assets.router)
app.include_router(market.router)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Market Intelligence Trading Signal System",
        "version": "1.0.0",
        "status": "running",
    }


@app.on_event("startup")
async def startup_event():
    """Application startup event."""
    logger.info("Market Intelligence Trading Signal System starting up")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Debug mode: {settings.debug}")

    # Don't run background jobs (hourly MEXC sync, market ingestion, etc.)
    # under the test suite.
    if settings.app_env != "testing":
        start_scheduler()
        await start_market_ingestion()
        # News ingestion has no persistent connection to hold (unlike
        # market data's WebSocket) -- this just builds the adapter set so
        # the scheduled poll job (every few minutes) has it ready. Safe to
        # call even if it later gets initialized lazily by the job itself.
        await start_news_ingestion()


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event."""
    logger.info("Market Intelligence Trading Signal System shutting down")
    if settings.app_env != "testing":
        shutdown_scheduler()
        await stop_market_ingestion()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
