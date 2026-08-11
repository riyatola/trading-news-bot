"""Database connection and session management."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from app.config.settings import get_settings
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

# Create database engine
engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connection before use
    echo=settings.debug,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Dependency: get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Configure connection on connect event.

    'SET search_path' is Postgres-specific syntax; skip it for other
    dialects (e.g. SQLite, used by the test suite / local scripts) so the
    same engine construction code works everywhere.
    """
    if engine.dialect.name != "postgresql":
        return
    cursor = dbapi_conn.cursor()
    cursor.execute("SET search_path TO public")
    cursor.close()
