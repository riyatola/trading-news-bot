"""Initial schema creation."""
from alembic import op
import sqlalchemy as sa

revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial schema."""
    # Create system_config table
    op.create_table(
        'system_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(100), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='unique_config_key'),
    )
    op.create_index('ix_system_config_key', 'system_config', ['key'])
    op.create_index('ix_system_config_category', 'system_config', ['category'])

    # Create assets table
    op.create_table(
        'assets',
        sa.Column('id', sa.String(10), nullable=False),
        sa.Column('ticker', sa.String(10), nullable=False),
        sa.Column('company_name', sa.String(255), nullable=False),
        sa.Column('mexc_symbol', sa.String(50), nullable=False),
        sa.Column('exchange_ticker', sa.String(50), nullable=False),
        sa.Column('sector', sa.String(100), nullable=False),
        sa.Column('industry', sa.String(100), nullable=False),
        sa.Column('country', sa.String(3), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticker', name='unique_ticker'),
        sa.UniqueConstraint('mexc_symbol', name='unique_mexc_symbol'),
    )
    op.create_index('ix_assets_ticker', 'assets', ['ticker'])
    op.create_index('ix_assets_mexc_symbol', 'assets', ['mexc_symbol'])
    op.create_index('ix_assets_active', 'assets', ['active'])
    op.create_index('ix_assets_sector', 'assets', ['sector'])
    op.create_index('ix_assets_industry', 'assets', ['industry'])

    # Create asset_relationships table
    op.create_table(
        'asset_relationships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_asset_id', sa.String(10), nullable=False),
        sa.Column('target_asset_id', sa.String(10), nullable=False),
        sa.Column('relationship_type', sa.String(50), nullable=False),
        sa.Column('strength', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('direction', sa.String(50), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('source', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_asset_id'], ['assets.id']),
        sa.ForeignKeyConstraint(['target_asset_id'], ['assets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_asset_id', 'target_asset_id', 'relationship_type', name='unique_relationship'),
    )
    op.create_index('ix_asset_relationships_source_asset_id', 'asset_relationships', ['source_asset_id'])
    op.create_index('ix_asset_relationships_target_asset_id', 'asset_relationships', ['target_asset_id'])

    # Create sources table
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('credibility_tier', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('credibility_score', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='unique_source_name'),
    )
    op.create_index('ix_sources_source_type', 'sources', ['source_type'])

    # Create source_accounts table
    op.create_table(
        'source_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.String(255), nullable=False),
        sa.Column('account_name', sa.String(255), nullable=False),
        sa.Column('account_type', sa.String(50), nullable=True),
        sa.Column('credibility_score', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'account_id', name='unique_source_account'),
    )
    op.create_index('ix_source_accounts_source_id', 'source_accounts', ['source_id'])

    # Create raw_events table (immutable)
    op.create_table(
        'raw_events',
        sa.Column('id', sa.String(100), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('source_account_id', sa.Integer(), nullable=True),
        sa.Column('source_event_id', sa.String(255), nullable=True),
        sa.Column('author', sa.String(255), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('language', sa.String(10), nullable=False, server_default='en'),
        sa.Column('raw_metadata', sa.JSON(), nullable=True),
        sa.Column('ingested_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id']),
        sa.ForeignKeyConstraint(['source_account_id'], ['source_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'source_event_id', name='unique_raw_event'),
    )
    op.create_index('ix_raw_events_source_id', 'raw_events', ['source_id'])
    op.create_index('ix_raw_events_published_at', 'raw_events', ['published_at'])
    op.create_index('ix_raw_events_ingested_at', 'raw_events', ['ingested_at'])

    # Create events table
    op.create_table(
        'events',
        sa.Column('id', sa.String(100), nullable=False),
        sa.Column('event_cluster_id', sa.String(100), nullable=True),
        sa.Column('raw_event_id', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=True),
        sa.Column('direction', sa.String(20), nullable=True),
        sa.Column('severity', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('time_horizon', sa.String(50), nullable=True),
        sa.Column('novelty', sa.Integer(), nullable=True),
        sa.Column('macro_relevance', sa.Integer(), nullable=True),
        sa.Column('catalyst', sa.String(255), nullable=True),
        sa.Column('reasoning_summary', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('is_reprocessable', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['raw_event_id'], ['raw_events.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_events_event_cluster_id', 'events', ['event_cluster_id'])
    op.create_index('ix_events_raw_event_id', 'events', ['raw_event_id'])
    op.create_index('ix_events_event_type', 'events', ['event_type'])
    op.create_index('ix_events_direction', 'events', ['direction'])
    op.create_index('ix_events_processed_at', 'events', ['processed_at'])
    op.create_index('ix_events_created_at', 'events', ['created_at'])
    op.create_index('ix_events_updated_at', 'events', ['updated_at'])

    # Create event_entities table
    op.create_table(
        'event_entities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('asset_id', sa.String(10), nullable=False),
        sa.Column('relationship', sa.String(50), nullable=True),
        sa.Column('direction', sa.String(20), nullable=True),
        sa.Column('impact', sa.String(255), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_event_entities_event_id', 'event_entities', ['event_id'])
    op.create_index('ix_event_entities_asset_id', 'event_entities', ['asset_id'])

    # Create event_impacts table
    op.create_table(
        'event_impacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('macro_relevance', sa.JSON(), nullable=True),
        sa.Column('cross_asset_effects', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', name='unique_event_impact'),
    )

    # Create market_snapshots table
    op.create_table(
        'market_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.String(10), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('mark_price', sa.Float(), nullable=True),
        sa.Column('index_price', sa.Float(), nullable=True),
        sa.Column('volume_24h', sa.Float(), nullable=True),
        sa.Column('volume_1h', sa.Float(), nullable=True),
        sa.Column('open_interest', sa.Float(), nullable=True),
        sa.Column('funding_rate', sa.Float(), nullable=True),
        sa.Column('basis', sa.Float(), nullable=True),
        sa.Column('indicators', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_id', 'timestamp', name='unique_market_snapshot'),
    )
    op.create_index('ix_market_snapshots_asset_id', 'market_snapshots', ['asset_id'])
    op.create_index('ix_market_snapshots_timestamp', 'market_snapshots', ['timestamp'])

    # Create macro_snapshots table
    op.create_table(
        'macro_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('fed_funds_rate', sa.Float(), nullable=True),
        sa.Column('treasury_2y', sa.Float(), nullable=True),
        sa.Column('treasury_10y', sa.Float(), nullable=True),
        sa.Column('treasury_30y', sa.Float(), nullable=True),
        sa.Column('real_yields', sa.Float(), nullable=True),
        sa.Column('cpi', sa.Float(), nullable=True),
        sa.Column('pce', sa.Float(), nullable=True),
        sa.Column('ppi', sa.Float(), nullable=True),
        sa.Column('nfp', sa.Float(), nullable=True),
        sa.Column('unemployment_rate', sa.Float(), nullable=True),
        sa.Column('jobless_claims', sa.Float(), nullable=True),
        sa.Column('gdp', sa.Float(), nullable=True),
        sa.Column('pmi', sa.Float(), nullable=True),
        sa.Column('ism', sa.Float(), nullable=True),
        sa.Column('vix', sa.Float(), nullable=True),
        sa.Column('dxy', sa.Float(), nullable=True),
        sa.Column('sp500', sa.Float(), nullable=True),
        sa.Column('nasdaq', sa.Float(), nullable=True),
        sa.Column('wti', sa.Float(), nullable=True),
        sa.Column('brent', sa.Float(), nullable=True),
        sa.Column('gold', sa.Float(), nullable=True),
        sa.Column('copper', sa.Float(), nullable=True),
        sa.Column('usd_cny', sa.Float(), nullable=True),
        sa.Column('usd_jpy', sa.Float(), nullable=True),
        sa.Column('eur_usd', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('timestamp', name='unique_macro_snapshot'),
    )
    op.create_index('ix_macro_snapshots_timestamp', 'macro_snapshots', ['timestamp'])

    # Create opportunities table
    op.create_table(
        'opportunities',
        sa.Column('id', sa.String(100), nullable=False),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('asset_id', sa.String(10), nullable=False),
        sa.Column('opportunity_type', sa.String(50), nullable=True),
        sa.Column('long_score', sa.Integer(), nullable=True),
        sa.Column('short_score', sa.Integer(), nullable=True),
        sa.Column('macro_score', sa.Integer(), nullable=True),
        sa.Column('score_components', sa.JSON(), nullable=True),
        sa.Column('market_confirmation_available', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_opportunities_event_id', 'opportunities', ['event_id'])
    op.create_index('ix_opportunities_asset_id', 'opportunities', ['asset_id'])
    op.create_index('ix_opportunities_opportunity_type', 'opportunities', ['opportunity_type'])
    op.create_index('ix_opportunities_status', 'opportunities', ['status'])
    op.create_index('ix_opportunities_created_at', 'opportunities', ['created_at'])
    op.create_index('ix_opportunities_updated_at', 'opportunities', ['updated_at'])

    # Create alerts table
    op.create_table(
        'alerts',
        sa.Column('id', sa.String(100), nullable=False),
        sa.Column('opportunity_id', sa.String(100), nullable=False),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('telegram_message_id', sa.String(255), nullable=True),
        sa.Column('telegram_channel', sa.String(100), nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('delivery_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_alerts_opportunity_id', 'alerts', ['opportunity_id'])
    op.create_index('ix_alerts_alert_type', 'alerts', ['alert_type'])
    op.create_index('ix_alerts_status', 'alerts', ['status'])
    op.create_index('ix_alerts_created_at', 'alerts', ['created_at'])

    # Create theses table
    op.create_table(
        'theses',
        sa.Column('id', sa.String(100), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('current_confidence', sa.Integer(), nullable=True),
        sa.Column('previous_confidence', sa.Integer(), nullable=True),
        sa.Column('confidence_change', sa.String(50), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_theses_status', 'theses', ['status'])

    # Create thesis_assets table
    op.create_table(
        'thesis_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('thesis_id', sa.String(100), nullable=False),
        sa.Column('asset_id', sa.String(10), nullable=False),
        sa.Column('relevance', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['thesis_id'], ['theses.id']),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('thesis_id', 'asset_id', name='unique_thesis_asset'),
    )
    op.create_index('ix_thesis_assets_thesis_id', 'thesis_assets', ['thesis_id'])

    # Create thesis_evidence table
    op.create_table(
        'thesis_evidence',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('thesis_id', sa.String(100), nullable=False),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('evidence_type', sa.String(50), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['thesis_id'], ['theses.id']),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('thesis_id', 'event_id', name='unique_thesis_evidence'),
    )
    op.create_index('ix_thesis_evidence_thesis_id', 'thesis_evidence', ['thesis_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_thesis_evidence_thesis_id', table_name='thesis_evidence')
    op.drop_table('thesis_evidence')
    op.drop_index('ix_thesis_assets_thesis_id', table_name='thesis_assets')
    op.drop_table('thesis_assets')
    op.drop_index('ix_theses_status', table_name='theses')
    op.drop_table('theses')
    op.drop_index('ix_alerts_created_at', table_name='alerts')
    op.drop_index('ix_alerts_status', table_name='alerts')
    op.drop_index('ix_alerts_alert_type', table_name='alerts')
    op.drop_index('ix_alerts_opportunity_id', table_name='alerts')
    op.drop_table('alerts')
    op.drop_index('ix_opportunities_updated_at', table_name='opportunities')
    op.drop_index('ix_opportunities_created_at', table_name='opportunities')
    op.drop_index('ix_opportunities_status', table_name='opportunities')
    op.drop_index('ix_opportunities_opportunity_type', table_name='opportunities')
    op.drop_index('ix_opportunities_asset_id', table_name='opportunities')
    op.drop_index('ix_opportunities_event_id', table_name='opportunities')
    op.drop_table('opportunities')
    op.drop_index('ix_macro_snapshots_timestamp', table_name='macro_snapshots')
    op.drop_table('macro_snapshots')
    op.drop_index('ix_market_snapshots_timestamp', table_name='market_snapshots')
    op.drop_index('ix_market_snapshots_asset_id', table_name='market_snapshots')
    op.drop_table('market_snapshots')
    op.drop_table('event_impacts')
    op.drop_index('ix_event_entities_asset_id', table_name='event_entities')
    op.drop_index('ix_event_entities_event_id', table_name='event_entities')
    op.drop_table('event_entities')
    op.drop_index('ix_events_updated_at', table_name='events')
    op.drop_index('ix_events_created_at', table_name='events')
    op.drop_index('ix_events_processed_at', table_name='events')
    op.drop_index('ix_events_direction', table_name='events')
    op.drop_index('ix_events_event_type', table_name='events')
    op.drop_index('ix_events_raw_event_id', table_name='events')
    op.drop_index('ix_events_event_cluster_id', table_name='events')
    op.drop_table('events')
    op.drop_index('ix_raw_events_ingested_at', table_name='raw_events')
    op.drop_index('ix_raw_events_published_at', table_name='raw_events')
    op.drop_index('ix_raw_events_source_id', table_name='raw_events')
    op.drop_table('raw_events')
    op.drop_index('ix_source_accounts_source_id', table_name='source_accounts')
    op.drop_table('source_accounts')
    op.drop_index('ix_sources_source_type', table_name='sources')
    op.drop_table('sources')
    op.drop_index('ix_asset_relationships_target_asset_id', table_name='asset_relationships')
    op.drop_index('ix_asset_relationships_source_asset_id', table_name='asset_relationships')
    op.drop_table('asset_relationships')
    op.drop_index('ix_assets_industry', table_name='assets')
    op.drop_index('ix_assets_sector', table_name='assets')
    op.drop_index('ix_assets_active', table_name='assets')
    op.drop_index('ix_assets_mexc_symbol', table_name='assets')
    op.drop_index('ix_assets_ticker', table_name='assets')
    op.drop_table('assets')
    op.drop_index('ix_system_config_category', table_name='system_config')
    op.drop_index('ix_system_config_key', table_name='system_config')
    op.drop_table('system_config')
