"""Add ai_spend_log table (Sprint 5: AI analysis cost tracking)."""
from alembic import op
import sqlalchemy as sa

revision = '002_ai_spend_log'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_spend_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_spend_log_event_id', 'ai_spend_log', ['event_id'])
    op.create_index('ix_ai_spend_log_created_at', 'ai_spend_log', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_ai_spend_log_created_at', table_name='ai_spend_log')
    op.drop_index('ix_ai_spend_log_event_id', table_name='ai_spend_log')
    op.drop_table('ai_spend_log')
