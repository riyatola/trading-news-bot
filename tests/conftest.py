"""Pytest configuration and fixtures."""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.db.models import Base
from app.config.settings import Settings
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="session")
def test_settings():
    """Test settings with in-memory SQLite database."""
    return Settings(
        database_url="sqlite:///:memory:",
        redis_url="redis://localhost:6379/1",  # Use separate DB for testing
        app_env="testing",
        debug=True,
    )


@pytest.fixture(scope="session")
def test_engine(test_settings):
    """Create test database engine."""
    engine = create_engine(
        test_settings.database_url,
        connect_args={"check_same_thread": False} if "sqlite" in test_settings.database_url else {},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(test_engine):
    """Create a new database session for each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(autocommit=False, autoflush=False, bind=connection)()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    """FastAPI test client with test database session."""
    def override_get_db():
        yield db_session
    
    from app.db.database import get_db
    app.dependency_overrides[get_db] = override_get_db
    
    test_client = TestClient(app)
    yield test_client
    
    app.dependency_overrides.clear()
