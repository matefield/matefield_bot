"""Add tebex payments and package integration

Revision ID: i5e6a7b8c9d0
Revises: h4d5e6a7b8c9
Create Date: 2026-09-22 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'i5e6a7b8c9d0'
down_revision: str | Sequence[str] | None = 'h4d5e6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add tebex_package_id to membership_types
    op.add_column('membership_types', sa.Column('tebex_package_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_membership_types_tebex_package_id'), 'membership_types', ['tebex_package_id'], unique=False)

    # 2. Add tebex tracking columns to memberships
    op.add_column('memberships', sa.Column('tebex_transaction_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_memberships_tebex_transaction_id'), 'memberships', ['tebex_transaction_id'], unique=False)

    op.add_column('memberships', sa.Column('tebex_subscription_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_memberships_tebex_subscription_id'), 'memberships', ['tebex_subscription_id'], unique=False)

    op.add_column('memberships', sa.Column('payment_source', sa.String(length=30), nullable=False, server_default='MANUAL'))

    # 3. Create payment_records table for idempotency and audit log
    op.create_table(
        'payment_records',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('steam_id', sa.String(), nullable=True),
        sa.Column('discord_id', sa.String(), nullable=True),
        sa.Column('package_id', sa.Integer(), nullable=True),
        sa.Column('package_name', sa.String(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='USD'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='COMPLETED'),
        sa.Column('raw_payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payment_records_transaction_id'), 'payment_records', ['transaction_id'], unique=True)
    op.create_index(op.f('ix_payment_records_event_type'), 'payment_records', ['event_type'], unique=False)
    op.create_index(op.f('ix_payment_records_steam_id'), 'payment_records', ['steam_id'], unique=False)
    op.create_index(op.f('ix_payment_records_discord_id'), 'payment_records', ['discord_id'], unique=False)
    op.create_index(op.f('ix_payment_records_package_id'), 'payment_records', ['package_id'], unique=False)
    op.create_index(op.f('ix_payment_records_status'), 'payment_records', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_payment_records_status'), table_name='payment_records')
    op.drop_index(op.f('ix_payment_records_package_id'), table_name='payment_records')
    op.drop_index(op.f('ix_payment_records_discord_id'), table_name='payment_records')
    op.drop_index(op.f('ix_payment_records_steam_id'), table_name='payment_records')
    op.drop_index(op.f('ix_payment_records_event_type'), table_name='payment_records')
    op.drop_index(op.f('ix_payment_records_transaction_id'), table_name='payment_records')
    op.drop_table('payment_records')

    op.drop_column('memberships', 'payment_source')
    op.drop_index(op.f('ix_memberships_tebex_subscription_id'), table_name='memberships')
    op.drop_column('memberships', 'tebex_subscription_id')
    op.drop_index(op.f('ix_memberships_tebex_transaction_id'), table_name='memberships')
    op.drop_column('memberships', 'tebex_transaction_id')

    op.drop_index(op.f('ix_membership_types_tebex_package_id'), table_name='membership_types')
    op.drop_column('membership_types', 'tebex_package_id')
