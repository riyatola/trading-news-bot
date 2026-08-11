"""Database models for Sprint 1+ foundation."""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, Text, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class SystemConfig(Base):
    """System configuration table for all weights, thresholds, and SLA targets."""
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=False)  # Store any type of value as JSON
    description = Column(Text)
    category = Column(String(100), index=True)  # e.g., "scoring", "sla", "ai_cost"
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('key', name='unique_config_key'),)


class Asset(Base):
    """MEXC stock perpetual assets (52 initial universe)."""
    __tablename__ = "assets"
    
    id = Column(String(10), primary_key=True)  # AST-01, AST-02, etc.
    ticker = Column(String(10), nullable=False, unique=True, index=True)
    company_name = Column(String(255), nullable=False)
    mexc_symbol = Column(String(50), nullable=False, unique=True, index=True)
    exchange_ticker = Column(String(50), nullable=False)
    sector = Column(String(100), nullable=False, index=True)
    industry = Column(String(100), nullable=False, index=True)
    country = Column(String(3), nullable=False)  # ISO 3166-1 alpha-2
    currency = Column(String(3), nullable=False, default="USD")
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AssetRelationship(Base):
    """Relationships between assets (manually seeded, quarterly refresh)."""
    __tablename__ = "asset_relationships"
    
    id = Column(Integer, primary_key=True)
    source_asset_id = Column(String(10), ForeignKey("assets.id"), nullable=False, index=True)
    target_asset_id = Column(String(10), ForeignKey("assets.id"), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=False)  # e.g., "competitor", "supplier", "customer"
    strength = Column(Float, default=0.5)  # 0-1 scale
    direction = Column(String(50))  # e.g., "positive", "negative", "neutral"
    confidence = Column(Float, default=0.5)  # 0-1 scale
    source = Column(String(255))  # e.g., "10-K", "sector-map", "manual"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('source_asset_id', 'target_asset_id', 'relationship_type', name='unique_relationship'),)


class Source(Base):
    """News/data sources with credibility scoring."""
    __tablename__ = "sources"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    source_type = Column(String(50), nullable=False, index=True)  # e.g., "news", "sec", "company_ir", "x", "macro"
    credibility_tier = Column(Integer, default=1)  # 1-4: 1=highest, 4=lowest
    credibility_score = Column(Float, default=0.5)  # 0-1 scale; static at launch
    url = Column(String(500))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SourceAccount(Base):
    """Individual accounts/authors within a source (e.g., CEO accounts on X)."""
    __tablename__ = "source_accounts"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    account_id = Column(String(255), nullable=False)  # e.g., X user ID
    account_name = Column(String(255), nullable=False)
    account_type = Column(String(50))  # e.g., "ceo", "cfo", "regulator", "analyst"
    credibility_score = Column(Float, default=0.5)
    url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('source_id', 'account_id', name='unique_source_account'),)


class DeadLetterEvent(Base):
    """Ingestion failures that exhausted retries (Sprint 4).

    Recorded instead of silently dropping a source's poll cycle, per the
    project's "no silent failures" principle. Reviewed manually and not
    auto-retried -- a persistently-failing adapter (e.g. an expired API
    key or a renamed IR feed URL) needs a human, not a tighter retry loop.
    """
    __tablename__ = "dead_letter_events"

    id = Column(Integer, primary_key=True)
    source_name = Column(String(255), nullable=False, index=True)
    source_type = Column(String(50), nullable=False, index=True)
    error_message = Column(Text, nullable=False)
    attempts = Column(Integer, default=0)
    occurred_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved = Column(Boolean, default=False, index=True)


class RawEvent(Base):
    """Immutable raw event storage (never delete; foundation for auditing and reprocessing)."""
    __tablename__ = "raw_events"
    
    id = Column(String(100), primary_key=True)  # UUID or deterministic hash
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    source_account_id = Column(Integer, ForeignKey("source_accounts.id"))
    source_event_id = Column(String(255))  # External ID from source
    author = Column(String(255))
    published_at = Column(DateTime, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    url = Column(String(500))
    language = Column(String(10), default="en")
    raw_metadata = Column(JSON)  # Store source-specific metadata
    ingested_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (UniqueConstraint('source_id', 'source_event_id', name='unique_raw_event'),)


class Event(Base):
    """Processed event with AI analysis and deduplication."""
    __tablename__ = "events"
    
    id = Column(String(100), primary_key=True)
    event_cluster_id = Column(String(100), index=True)  # Group related stories
    raw_event_id = Column(String(100), ForeignKey("raw_events.id"), nullable=False, index=True)
    
    # Classification (AI output)
    event_type = Column(String(50), index=True)  # e.g., "earnings", "guidance", "regulation"
    direction = Column(String(20), index=True)  # "bullish", "bearish", "neutral", "mixed"
    severity = Column(Integer)  # 1-10 scale
    confidence = Column(Integer)  # 0-100 scale
    time_horizon = Column(String(50))  # e.g., "days", "weeks", "months"
    novelty = Column(Integer)  # 0-100: is this new information?
    macro_relevance = Column(Integer)  # 0-100: connection to macro variables
    
    # Catalyst and reasoning
    catalyst = Column(String(255))  # Short catalyst description
    reasoning_summary = Column(Text)  # Explanation from AI
    
    # Processing state
    processed_at = Column(DateTime, index=True)
    is_reprocessable = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EventEntity(Base):
    """Entities (assets) extracted from events."""
    __tablename__ = "event_entities"
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), ForeignKey("events.id"), nullable=False, index=True)
    asset_id = Column(String(10), ForeignKey("assets.id"), nullable=False, index=True)
    relationship = Column(String(50))  # "direct", "secondary", "tertiary"
    direction = Column(String(20))  # "bullish", "bearish", "neutral"
    impact = Column(String(255))  # Description of impact
    confidence = Column(Integer)  # 0-100
    created_at = Column(DateTime, default=datetime.utcnow)


class EventImpact(Base):
    """Impact analysis for events."""
    __tablename__ = "event_impacts"
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), ForeignKey("events.id"), nullable=False, unique=True)
    summary = Column(Text)
    macro_relevance = Column(JSON)  # Links to macro variables
    cross_asset_effects = Column(JSON)  # Other affected assets
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MarketSnapshot(Base):
    """MEXC market data snapshots (price, volume, OI, funding, etc.)."""
    __tablename__ = "market_snapshots"
    
    id = Column(Integer, primary_key=True)
    asset_id = Column(String(10), ForeignKey("assets.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    
    # Price data
    price = Column(Float, nullable=False)
    mark_price = Column(Float)
    index_price = Column(Float)
    
    # Volume and OI
    volume_24h = Column(Float)
    volume_1h = Column(Float)
    open_interest = Column(Float)
    
    # Funding
    funding_rate = Column(Float)
    basis = Column(Float)
    
    # Indicators (calculated)
    indicators = Column(JSON)  # 5m/15m/1h/4h/24h/7d/30d returns, volatility, etc.
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('asset_id', 'timestamp', name='unique_market_snapshot'),)


class MacroSnapshot(Base):
    """Macro data snapshots (rates, inflation, employment, etc.)."""
    __tablename__ = "macro_snapshots"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    
    # Rates
    fed_funds_rate = Column(Float)
    treasury_2y = Column(Float)
    treasury_10y = Column(Float)
    treasury_30y = Column(Float)
    real_yields = Column(Float)
    
    # Inflation
    cpi = Column(Float)
    pce = Column(Float)
    ppi = Column(Float)
    
    # Employment
    nfp = Column(Float)
    unemployment_rate = Column(Float)
    jobless_claims = Column(Float)
    
    # Economy
    gdp = Column(Float)
    pmi = Column(Float)
    ism = Column(Float)
    
    # Markets
    vix = Column(Float)
    dxy = Column(Float)
    sp500 = Column(Float)
    nasdaq = Column(Float)
    
    # Commodities
    wti = Column(Float)
    brent = Column(Float)
    gold = Column(Float)
    copper = Column(Float)
    
    # FX
    usd_cny = Column(Float)
    usd_jpy = Column(Float)
    eur_usd = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('timestamp', name='unique_macro_snapshot'),)


class Opportunity(Base):
    """Trading opportunities (LONG, SHORT, MACRO, etc.) with scoring breakdown."""
    __tablename__ = "opportunities"
    
    id = Column(String(100), primary_key=True)
    event_id = Column(String(100), ForeignKey("events.id"), nullable=False, index=True)
    asset_id = Column(String(10), ForeignKey("assets.id"), nullable=False, index=True)
    
    # Opportunity type and scores
    opportunity_type = Column(String(50), index=True)  # "LONG", "SHORT", "MACRO", "BREAKING", "MARKET_ANOMALY", "THESIS_CHANGE"
    long_score = Column(Integer)  # 0-100
    short_score = Column(Integer)  # 0-100
    macro_score = Column(Integer)  # 0-100
    
    # Score components
    score_components = Column(JSON)  # {catalyst: 80, direction: 90, source_quality: 75, ...}
    
    # Degraded mode flag
    market_confirmation_available = Column(Boolean, default=True)  # False when MEXC unavailable
    
    # Status
    status = Column(String(50), default="active", index=True)  # "active", "closed", "archived"
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class Alert(Base):
    """Alerts sent to Telegram."""
    __tablename__ = "alerts"
    
    id = Column(String(100), primary_key=True)
    opportunity_id = Column(String(100), ForeignKey("opportunities.id"), nullable=False, index=True)
    alert_type = Column(String(50), index=True)  # "BREAKING", "LONG", "SHORT", "MACRO", "MARKET", "DAILY"
    telegram_message_id = Column(String(255))
    telegram_channel = Column(String(100))
    
    # Content
    title = Column(String(500))
    body = Column(Text)
    
    # Status
    status = Column(String(50), default="pending", index=True)  # "pending", "sent", "failed", "retrying"
    delivery_attempts = Column(Integer, default=0)
    last_error = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    sent_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Thesis(Base):
    """User-created investment theses."""
    __tablename__ = "theses"
    
    id = Column(String(100), primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Confidence tracking
    current_confidence = Column(Integer)  # 0-100
    previous_confidence = Column(Integer)  # 0-100
    confidence_change = Column(String(50))  # "strengthening", "weakening", "stable"
    
    # Status
    status = Column(String(50), default="active", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ThesisAsset(Base):
    """Assets relevant to a thesis."""
    __tablename__ = "thesis_assets"
    
    id = Column(Integer, primary_key=True)
    thesis_id = Column(String(100), ForeignKey("theses.id"), nullable=False, index=True)
    asset_id = Column(String(10), ForeignKey("assets.id"), nullable=False, index=True)
    relevance = Column(Integer)  # 0-100
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('thesis_id', 'asset_id', name='unique_thesis_asset'),)


class AISpendLog(Base):
    """One row per successful LLM analysis call (Sprint 5).

    Used purely for cost accounting -- `app.intelligence.cost_tracker`
    sums `cost_usd` for the current UTC day against the configured daily
    cap (system_config key 'ai_daily_spend_cap_usd', falling back to
    Settings.ai_daily_spend_cap_usd) before allowing another LLM call.
    Kept append-only, mirroring raw_events' immutability -- it's also the
    audit trail for "why did we spend what we spent."
    """
    __tablename__ = "ai_spend_log"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), ForeignKey("events.id"), nullable=False, index=True)
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ThesisEvidence(Base):
    """Supporting and contradicting evidence for theses."""
    __tablename__ = "thesis_evidence"
    
    id = Column(Integer, primary_key=True)
    thesis_id = Column(String(100), ForeignKey("theses.id"), nullable=False, index=True)
    event_id = Column(String(100), ForeignKey("events.id"), nullable=False, index=True)
    evidence_type = Column(String(50), nullable=False)  # "supporting", "contradicting"
    weight = Column(Integer)  # 0-100: importance of this evidence
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('thesis_id', 'event_id', name='unique_thesis_evidence'),)
