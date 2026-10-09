"""Add membership_types table and server_id to memberships

Revision ID: h4d5e6a7b8c9
Revises: g3c4d5e6a7b8
Create Date: 2026-09-22 10:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'h4d5e6a7b8c9'
down_revision: str | Sequence[str] | None = 'g3c4d5e6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create membership_types table
    op.create_table(
        'membership_types',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('price_usd', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('billing_type', sa.String(length=20), nullable=False, server_default='ONE_TIME'),
        sa.Column('default_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('max_quota', sa.Integer(), nullable=True),
        sa.Column('discord_role_id', sa.String(), nullable=True),
        sa.Column('server_id', sa.Integer(), sa.ForeignKey('rcon_servers.id'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_membership_types_code'), 'membership_types', ['code'], unique=True)

    # 2. Add server_id column to memberships
    op.add_column('memberships', sa.Column('server_id', sa.Integer(), sa.ForeignKey('rcon_servers.id'), nullable=True))


def downgrade() -> None:
    op.drop_column('memberships', 'server_id')
    op.drop_index(op.f('ix_membership_types_code'), table_name='membership_types')
    op.drop_table('membership_types')
