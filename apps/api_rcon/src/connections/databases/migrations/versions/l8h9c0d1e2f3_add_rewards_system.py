"""Add rewards system (reward_items, reward_claims, reward_points, rewarded_seeding_seconds)

Revision ID: l8h9c0d1e2f3
Revises: k7g8b9c0d1e2
Create Date: 2026-09-27 12:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'l8h9c0d1e2f3'
down_revision: str | Sequence[str] | None = 'k7g8b9c0d1e2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add reward_points to players
    op.add_column('players', sa.Column('reward_points', sa.Integer(), server_default='0', nullable=False))

    # 2. Add rewarded_seeding_seconds to player_sessions
    op.add_column('player_sessions', sa.Column('rewarded_seeding_seconds', sa.Integer(), server_default='0', nullable=False))

    # 3. Create reward_items table
    op.create_table(
        'reward_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('cost_points', sa.Integer(), server_default='1', nullable=False),
        sa.Column('delivery_type', sa.String(), server_default='AUTOMATIC', nullable=False),
        sa.Column('reward_type', sa.String(), server_default='MEMBERSHIP', nullable=False),
        sa.Column('reward_value', sa.String(), server_default='', nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reward_items_code'), 'reward_items', ['code'], unique=True)

    # 4. Create reward_claims table
    op.create_table(
        'reward_claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('steam_id', sa.String(), nullable=False),
        sa.Column('reward_id', sa.Integer(), nullable=False),
        sa.Column('claim_code', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default='PENDING', nullable=False),
        sa.Column('points_spent', sa.Integer(), server_default='0', nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_by', sa.String(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['reward_id'], ['reward_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['steam_id'], ['players.steam_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reward_claims_claim_code'), 'reward_claims', ['claim_code'], unique=True)
    op.create_index(op.f('ix_reward_claims_reward_id'), 'reward_claims', ['reward_id'], unique=False)
    op.create_index(op.f('ix_reward_claims_status'), 'reward_claims', ['status'], unique=False)
    op.create_index(op.f('ix_reward_claims_steam_id'), 'reward_claims', ['steam_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reward_claims_steam_id'), table_name='reward_claims')
    op.drop_index(op.f('ix_reward_claims_status'), table_name='reward_claims')
    op.drop_index(op.f('ix_reward_claims_reward_id'), table_name='reward_claims')
    op.drop_index(op.f('ix_reward_claims_claim_code'), table_name='reward_claims')
    op.drop_table('reward_claims')

    op.drop_index(op.f('ix_reward_items_code'), table_name='reward_items')
    op.drop_table('reward_items')

    op.drop_column('player_sessions', 'rewarded_seeding_seconds')
    op.drop_column('players', 'reward_points')
