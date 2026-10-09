"""Drop discord_role_id from membership_types, add special_role_id to memberships, and backfill VIPs into player_roles

Revision ID: k7g8b9c0d1e2
Revises: j6f7a8b9c0d1
Create Date: 2026-09-25 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'k7g8b9c0d1e2'
down_revision: str | Sequence[str] | None = 'j6f7a8b9c0d1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add special_role_id to memberships for explicitly attached special badge roles
    op.add_column('memberships', sa.Column('special_role_id', sa.BigInteger(), sa.ForeignKey('roles.id', ondelete='SET NULL'), nullable=True))
    op.create_index(op.f('ix_memberships_special_role_id'), 'memberships', ['special_role_id'], unique=False)

    # 2. Preserve special/system roles previously saved in role_granted_id (e.g. membership 107)
    op.execute("""
        UPDATE memberships m
        SET special_role_id = m.role_granted_id
        FROM roles r
        WHERE m.role_granted_id = r.id AND r.role_type IN ('SPECIAL', 'SYSTEM');
    """)

    # 3. Backfill memberships.role_granted_id with the proper VIP role from membership_types
    op.execute("""
        UPDATE memberships m
        SET role_granted_id = mt.role_id
        FROM membership_types mt
        WHERE upper(m.type) = upper(mt.code);
    """)

    # 4. Drop redundant discord_role_id from membership_types (pure reference to roles table)
    op.drop_column('membership_types', 'discord_role_id')

    # 5. Populate player_roles for all currently active memberships that were missing their VIP role
    op.execute("""
        INSERT INTO player_roles (steam_id, role_id)
        SELECT DISTINCT m.steam_id, m.role_granted_id
        FROM memberships m
        WHERE m.is_active = true
          AND (m.end_date IS NULL OR m.end_date > NOW())
          AND m.role_granted_id IS NOT NULL
        ON CONFLICT (steam_id, role_id) DO NOTHING;
    """)

    # Also ensure active memberships with special_role_id are in player_roles
    op.execute("""
        INSERT INTO player_roles (steam_id, role_id)
        SELECT DISTINCT m.steam_id, m.special_role_id
        FROM memberships m
        WHERE m.is_active = true
          AND (m.end_date IS NULL OR m.end_date > NOW())
          AND m.special_role_id IS NOT NULL
        ON CONFLICT (steam_id, role_id) DO NOTHING;
    """)


def downgrade() -> None:
    # 1. Re-add discord_role_id to membership_types
    op.add_column('membership_types', sa.Column('discord_role_id', sa.String(), nullable=True))

    # 2. Populate discord_role_id from linked role
    op.execute("""
        UPDATE membership_types mt
        SET discord_role_id = r.discord_role_id
        FROM roles r
        WHERE mt.role_id = r.id;
    """)

    # 3. Drop special_role_id from memberships
    op.drop_index(op.f('ix_memberships_special_role_id'), table_name='memberships')
    op.drop_column('memberships', 'special_role_id')
