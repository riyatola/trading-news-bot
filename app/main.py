"""Main FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import get_settings
from app.config.logging_config import configure_logging
from app.db.database import engine
from app.db.models import Base
from app.api import health
import logging

# Configure logging
logger_instance = configure_logging()
logger = logging.getLogger(__name__)

# Initialize settings
settings = get_settings()

# Create database tables
Base.metadata.create_all(bind=engine)

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


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event."""
    logger.info("Market Intelligence Trading Signal System shutting down")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
