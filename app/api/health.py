"""Health check endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from redis import Redis
from app.db.database import get_db
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


def get_redis_connection():
    """Get Redis connection for health check."""
    from app.config.settings import get_settings
    settings = get_settings()
    try:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        redis_client.ping()
        return redis_client
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        raise


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint.
    
    Returns:
        dict: Health status with database and Redis connectivity information.
    """
    health_status = {
        "status": "ok",
        "database": "unknown",
        "redis": "unknown",
    }
    
    # Check database connectivity
    try:
        db.execute("SELECT 1")
        health_status["database"] = "ok"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["database"] = f"error: {str(e)}"
        logger.error(f"Database health check failed: {e}")
    
    # Check Redis connectivity
    try:
        redis_client = get_redis_connection()
        health_status["redis"] = "ok"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["redis"] = f"error: {str(e)}"
        logger.error(f"Redis health check failed: {e}")
    
    return health_status
