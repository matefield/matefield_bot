"""Add rcon_servers table
Revision ID: g3c4d5e6a7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-09-22 06:50:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'g3c4d5e6a7b8'
down_revision: str | Sequence[str] | None = 'f2b3c4d5e6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'rcon_servers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('ip', sa.String(), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('password', sa.String(), nullable=False),
        sa.Column('scheme', sa.String(length=10), nullable=False, server_default='http'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rcon_servers_name'), 'rcon_servers', ['name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rcon_servers_name'), table_name='rcon_servers')
    op.drop_table('rcon_servers')
