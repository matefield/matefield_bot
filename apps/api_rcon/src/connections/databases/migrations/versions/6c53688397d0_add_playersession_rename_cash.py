"""Add PlayerSession and rename cash_spent to cash_earned

Revision ID: 6c53688397d0
Revises: 8711d6c5c582
Create Date: 2026-09-11 21:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6c53688397d0'
down_revision: str | None = '8711d6c5c582'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create player_sessions table
    op.create_table('player_sessions',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('steam_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_seconds', sa.Integer(), nullable=False),
        sa.Column('seeding_seconds', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['steam_id'], ['players.steam_id'], ),
    )
    op.create_index(op.f('ix_player_sessions_steam_id'), 'player_sessions', ['steam_id'], unique=False)
    
    # Rename cash_spent to cash_earned
    op.alter_column('match_player_stats', 'cash_spent', new_column_name='cash_earned')


def downgrade() -> None:
    op.alter_column('match_player_stats', 'cash_earned', new_column_name='cash_spent')
    op.drop_index(op.f('ix_player_sessions_steam_id'), table_name='player_sessions')
    op.drop_table('player_sessions')
