import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure the app boots in test mode without background jobs or external services.
os.environ.setdefault("APP_ENV", "testing")

from app.api import assets as assets_api, health as health_api, market as market_api
from app.db.database import get_db
from app.db.models import Base
from app.main import app


@pytest.fixture()
def test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def db(db_session):
    yield db_session


@pytest.fixture()
def client(db_session, monkeypatch):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides.update({
        get_db: override_get_db,
        assets_api.get_db: override_get_db,
        market_api.get_db: override_get_db,
        health_api.get_db: override_get_db,
    })
    monkeypatch.setattr(health_api, "get_redis_connection", lambda: type("RedisStub", (), {"ping": lambda self: True})())

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
