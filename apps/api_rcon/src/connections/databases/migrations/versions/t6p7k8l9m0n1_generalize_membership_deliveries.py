"""Retain initial grants and expirations in the existing role delivery table."""
import json
import logging
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "t6p7k8l9m0n1"
down_revision = "s5o6j7k8l9m0"
logger = logging.getLogger("alembic.runtime.migration")

branch_labels = None
depends_on = None


def _snowflake(value):
    return (isinstance(value, str) and bool(value) and len(value) <= 20 and value[0] != "0"
            and value.isascii() and value.isdecimal() and 0 < int(value) < 2 ** 64)


def upgrade():
    with op.batch_alter_table("membership_renewal_deliveries") as batch:
        batch.alter_column("previous_membership_id", existing_type=sa.Integer(), nullable=True)

    connection = op.get_bind()
    metadata = sa.MetaData()
    memberships = sa.Table("memberships", metadata, autoload_with=connection)
    players = sa.Table("players", metadata, autoload_with=connection)
    bindings = sa.Table("role_discord_bindings", metadata, autoload_with=connection)
    roles = sa.Table("roles", metadata, autoload_with=connection)
    deliveries = sa.Table("membership_renewal_deliveries", metadata, autoload_with=connection)
    # Guild ownership is recorded only by Discord operations. Never infer a guild
    # or a historical administrator from legacy memberships or global role IDs.
    existing = set(connection.execute(sa.select(deliveries.c.membership_id)).scalars())
    now = datetime.now(timezone.utc)
    candidates = connection.execute(sa.select(memberships, players.c.discord_id).join(
        players, players.c.steam_id == memberships.c.steam_id,
    ).where(
        memberships.c.creation_operation_id.is_not(None), memberships.c.discord_guild_id.is_not(None),
        memberships.c.is_scheduled.is_(False),
        sa.or_(memberships.c.is_active.is_(True),
               sa.and_(memberships.c.end_date.is_not(None), memberships.c.end_date <= now)),
    )).mappings()
    for membership in candidates:
        if membership["id"] in existing or not _snowflake(membership["discord_guild_id"]) or not _snowflake(membership["discord_id"]):
            continue
        physical_roles = connection.execute(sa.select(
            bindings.c.discord_role_id, bindings.c.updated_at, roles.c.role_type, roles.c.id,
        ).join(roles, roles.c.id == bindings.c.role_id).where(
            bindings.c.guild_id == membership["discord_guild_id"],
            bindings.c.role_id.in_([membership["role_granted_id"], membership["special_role_id"]]),
        ).order_by(roles.c.id)).all()
        start = membership["start_date"]
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
        vip_binding = next((row for row in physical_roles if row.id == membership["role_granted_id"] and row.role_type == "VIP"), None)
        binding_time = vip_binding.updated_at if vip_binding else None
        if binding_time and binding_time.tzinfo is None:
            binding_time = binding_time.replace(tzinfo=timezone.utc)
        if not vip_binding or not _snowflake(vip_binding.discord_role_id) or binding_time is None or binding_time > start:
            logger.warning("membership_delivery_backfill_skipped membership_id=%s reason=uncertain_vip_binding", membership["id"])
            continue
        add = [row.discord_role_id for row in physical_roles if _snowflake(row.discord_role_id)]
        remove = [row.discord_role_id for row in physical_roles
                  if row.id == membership["role_granted_id"] and row.role_type == "VIP" and _snowflake(row.discord_role_id)]
        common = dict(membership_id=membership["id"], previous_membership_id=None,
                      guild_id=membership["discord_guild_id"], user_id=membership["discord_id"],
                      actor_id="0", completed=False, cancelled=False, created_at=now)
        if membership["is_active"]:
            connection.execute(deliveries.insert().values(
                **common, phase="START", available_at=membership["start_date"], activated=True,
                role_ids_to_add_json=json.dumps(add), role_ids_to_remove_json="[]",
            ))
        if membership["end_date"] is not None:
            connection.execute(deliveries.insert().values(
                **common, phase="END", available_at=membership["end_date"], activated=False,
                role_ids_to_add_json="[]", role_ids_to_remove_json=json.dumps(remove),
            ))


def downgrade():
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM membership_renewal_deliveries WHERE previous_membership_id IS NULL"))
    with op.batch_alter_table("membership_renewal_deliveries") as batch:
        batch.alter_column("previous_membership_id", existing_type=sa.Integer(), nullable=False)
