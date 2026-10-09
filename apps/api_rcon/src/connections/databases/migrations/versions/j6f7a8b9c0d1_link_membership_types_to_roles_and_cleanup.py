"""Link membership types to roles, add base_price_usd, and cleanup legacy tables

Revision ID: j6f7a8b9c0d1
Revises: i5e6a7b8c9d0
Create Date: 2026-09-25 14:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'j6f7a8b9c0d1'
down_revision: str | Sequence[str] | None = 'i5e6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add base_price_usd and role_id to membership_types
    op.add_column('membership_types', sa.Column('base_price_usd', sa.Float(), server_default='0.0', nullable=False))
    op.add_column('membership_types', sa.Column('role_id', sa.Integer(), sa.ForeignKey('roles.id', ondelete='SET NULL'), nullable=True))
    op.create_index(op.f('ix_membership_types_role_id'), 'membership_types', ['role_id'], unique=False)

    # 2. Populate role_id and base_price_usd from existing roles
    op.execute("""
        UPDATE membership_types mt
        SET role_id = r.id
        FROM roles r
        WHERE mt.discord_role_id = r.discord_role_id;
    """)

    # Explicit base prices for known tiers (Real vs Tebex with fees)
    op.execute("UPDATE membership_types SET base_price_usd = 5.0, price_usd = 6.0, role_id = 2 WHERE code = 'VIP_COMUN';")
    op.execute("UPDATE membership_types SET base_price_usd = 3.0, price_usd = 4.0, role_id = 3 WHERE code = 'VIP_EXPRESS';")
    op.execute("UPDATE membership_types SET base_price_usd = 0.0, price_usd = 0.0, role_id = 6 WHERE code = 'VIP_PERMANENTE';")
    op.execute("UPDATE membership_types SET base_price_usd = 0.0, price_usd = 0.0, role_id = 3 WHERE code = 'VIP_SEED';")

    # 3. Drop obsolete table membership_type_configs
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'membership_type_configs' in insp.get_table_names():
        op.drop_table('membership_type_configs')

    # 4. Clean up legacy bot_config keys
    op.execute("""
        DELETE FROM bot_config
        WHERE config_key LIKE 'ROLE_MAP_%'
           OR config_key LIKE 'ROLE_DAYS_%'
           OR config_key IN ('VIP_ROLE_IDS', 'ADMIN_ROLE_ID', 'OWNER_ROLE_ID');
    """)


def downgrade() -> None:
    # 1. Re-create membership_type_configs
    op.create_table(
        'membership_type_configs',
        sa.Column('membership_type', sa.String(), primary_key=True),
        sa.Column('max_quota', sa.Integer(), nullable=True),
    )

    # 2. Drop columns from membership_types
    op.drop_index(op.f('ix_membership_types_role_id'), table_name='membership_types')
    op.drop_column('membership_types', 'role_id')
    op.drop_column('membership_types', 'base_price_usd')
