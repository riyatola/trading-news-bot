"""Tests for database models and configuration."""
import pytest
from sqlalchemy import inspect
from app.db.models import (
    SystemConfig, Asset, AssetRelationship, Source, SourceAccount,
    RawEvent, Event, EventEntity, EventImpact, MarketSnapshot,
    MacroSnapshot, Opportunity, Alert, Thesis, ThesisAsset, ThesisEvidence
)
from datetime import datetime


class TestDatabaseSchema:
    """Test database schema creation."""
    
    def test_system_config_table_exists(self, test_engine):
        """Test system_config table exists."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "system_config" in tables
    
    def test_assets_table_exists(self, test_engine):
        """Test assets table exists."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "assets" in tables
    
    def test_raw_events_table_exists(self, test_engine):
        """Test raw_events table exists."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "raw_events" in tables
    
    def test_events_table_exists(self, test_engine):
        """Test events table exists."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "events" in tables
    
    def test_opportunities_table_exists(self, test_engine):
        """Test opportunities table exists."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "opportunities" in tables
    
    def test_all_required_tables_exist(self, test_engine):
        """Test all required tables exist."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        
        required_tables = [
            "system_config", "assets", "asset_relationships", "sources",
            "source_accounts", "raw_events", "events", "event_entities",
            "event_impacts", "market_snapshots", "macro_snapshots",
            "opportunities", "alerts", "theses", "thesis_assets", "thesis_evidence"
        ]
        
        for table in required_tables:
            assert table in tables, f"Missing table: {table}"


class TestSystemConfig:
    """Test SystemConfig model."""
    
    def test_create_system_config(self, db_session):
        """Test creating a system config entry."""
        config = SystemConfig(
            key="ai_daily_spend_cap",
            value={"amount": 100, "currency": "USD"},
            category="ai_cost"
        )
        db_session.add(config)
        db_session.commit()
        
        retrieved = db_session.query(SystemConfig).filter_by(key="ai_daily_spend_cap").first()
        assert retrieved is not None
        assert retrieved.value["amount"] == 100
        assert retrieved.category == "ai_cost"
    
    def test_system_config_unique_key(self, db_session):
        """Test system config key uniqueness."""
        config1 = SystemConfig(key="test_key", value={"data": "value1"})
        config2 = SystemConfig(key="test_key", value={"data": "value2"})
        
        db_session.add(config1)
        db_session.commit()
        
        db_session.add(config2)
        with pytest.raises(Exception):  # Should raise integrity error
            db_session.commit()


class TestAsset:
    """Test Asset model."""
    
    def test_create_asset(self, db_session):
        """Test creating an asset."""
        asset = Asset(
            id="AST-01",
            ticker="NVDA",
            company_name="NVIDIA Corporation",
            mexc_symbol="NVDAUSDT",
            exchange_ticker="NASDAQ:NVDA",
            sector="Technology",
            industry="Semiconductors",
            country="US",
            currency="USD",
            active=True
        )
        db_session.add(asset)
        db_session.commit()
        
        retrieved = db_session.query(Asset).filter_by(ticker="NVDA").first()
        assert retrieved is not None
        assert retrieved.company_name == "NVIDIA Corporation"
        assert retrieved.active is True
    
    def test_asset_ticker_uniqueness(self, db_session):
        """Test asset ticker uniqueness."""
        asset1 = Asset(
            id="AST-01",
            ticker="NVDA",
            company_name="NVIDIA",
            mexc_symbol="NVDAUSDT",
            exchange_ticker="NASDAQ:NVDA",
            sector="Technology",
            industry="Semiconductors",
            country="US"
        )
        asset2 = Asset(
            id="AST-02",
            ticker="NVDA",
            company_name="NVIDIA 2",
            mexc_symbol="NVDA2USDT",
            exchange_ticker="NASDAQ:NVDA",
            sector="Technology",
            industry="Semiconductors",
            country="US"
        )
        
        db_session.add(asset1)
        db_session.commit()
        
        db_session.add(asset2)
        with pytest.raises(Exception):  # Should raise integrity error
            db_session.commit()


class TestSource:
    """Test Source model."""
    
    def test_create_source(self, db_session):
        """Test creating a source."""
        source = Source(
            name="Reuters",
            source_type="news",
            credibility_tier=1,
            credibility_score=0.95,
            url="https://reuters.com"
        )
        db_session.add(source)
        db_session.commit()
        
        retrieved = db_session.query(Source).filter_by(name="Reuters").first()
        assert retrieved is not None
        assert retrieved.credibility_tier == 1
        assert retrieved.credibility_score == 0.95


class TestRawEvent:
    """Test RawEvent model."""
    
    def test_create_raw_event(self, db_session):
        """Test creating a raw event."""
        source = Source(name="TestSource", source_type="news")
        db_session.add(source)
        db_session.commit()
        
        event = RawEvent(
            id="raw-event-001",
            source_id=source.id,
            author="Test Author",
            published_at=datetime.utcnow(),
            title="Test Event",
            content="Test content",
            url="https://example.com",
            language="en"
        )
        db_session.add(event)
        db_session.commit()
        
        retrieved = db_session.query(RawEvent).filter_by(id="raw-event-001").first()
        assert retrieved is not None
        assert retrieved.title == "Test Event"
        assert retrieved.language == "en"
