"""Verify the delivery backfill against a disposable PostgreSQL database."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from test_membership_concurrency_postgres import postgres_engine
from src.connections.databases.db import (
    Membership, MembershipRenewalDelivery, Player, Role, RoleDiscordBinding,
)

GUILD = "222222222222222224"
VIP = "444444444444444447"
BADGE = "444444444444444448"
MIGRATION = Path(__file__).resolve().parents[1] / (
    "src/connections/databases/migrations/versions/"
    "u7q8l9m0n1o2_generalize_membership_deliveries.py"
)


def migration():
    specification = importlib.util.spec_from_file_location("initial_membership_deliveries", MIGRATION)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def run_migration(connection, direction):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


async def seed_previous_schema(engine):
    """The existing model differs from the prior schema only in this nullable FK."""
    async with engine.begin() as connection:
        await connection.execute(text(
            "ALTER TABLE membership_renewal_deliveries ALTER COLUMN previous_membership_id SET NOT NULL"
        ))
    now = datetime.now(timezone.utc)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all([
            Role(id=21, code="VIP_NORMAL", name="VIP Normal", role_type="VIP"),
            Role(id=11, code="FOUNDER", name="Fundador", role_type="SPECIAL"),
        ])
        await session.flush()
        session.add_all([
            RoleDiscordBinding(role_id=21, guild_id=GUILD, discord_role_id=VIP, configured_by=GUILD,
                               created_at=now - timedelta(days=2), updated_at=now - timedelta(days=2)),
            RoleDiscordBinding(role_id=11, guild_id=GUILD, discord_role_id=BADGE, configured_by=GUILD,
                               created_at=now - timedelta(days=2), updated_at=now - timedelta(days=2)),
            RoleDiscordBinding(role_id=21, guild_id="222222222222222225", discord_role_id=VIP,
                               configured_by=GUILD, updated_at=now),
        ])
        for identifier in range(1, 12):
            steam = str(76561198000001000 + identifier)
            user = "011111111111111111" if identifier == 6 else str(111111111111111100 + identifier)
            session.add(Player(steam_id=steam, discord_id=user))
            await session.flush()
            session.add(Membership(
                id=identifier, steam_id=steam, membership_type="regular", role_granted_id=21,
                special_role_id=11, start_time=now - timedelta(days=1),
                end_time=None if identifier == 2 else (
                    now - timedelta(hours=1) if identifier in (8, 11) else now + timedelta(days=30)
                ),
                is_active=identifier not in (3, 8, 9, 11), is_scheduled=identifier == 3,
                discord_guild_id=None if identifier == 4 else (
                    "022222222222222224" if identifier == 5 else (
                        "222222222222222225" if identifier == 11 else GUILD
                    )
                ),
                creation_operation_id=None if identifier == 7 else f"existing-discord-{identifier}",
            ))
        await session.flush()
        for identifier in (3, 10):
            for phase in ("START", "END"):
                session.add(MembershipRenewalDelivery(
                    membership_id=identifier, previous_membership_id=1, phase=phase,
                    guild_id=GUILD, actor_id=GUILD, user_id=str(111111111111111100 + identifier),
                    role_ids_to_add_json=json.dumps([VIP]) if phase == "START" else "[]",
                    role_ids_to_remove_json=json.dumps([VIP]) if phase == "END" else "[]",
                    available_at=now + timedelta(days=30), activated=identifier == 10,
                    completed=identifier == 10,
                ))
        await session.commit()


async def receipts(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        rows = (await session.exec(select(MembershipRenewalDelivery).order_by(
            MembershipRenewalDelivery.membership_id, MembershipRenewalDelivery.phase,
        ))).all()
        return {(row.membership_id, row.phase): row for row in rows}


@pytest.mark.asyncio
async def test_backfill_covers_known_discord_grants_and_expired_users_without_inventing_ownership(postgres_engine):
    await seed_previous_schema(postgres_engine)
    async with postgres_engine.begin() as connection:
        await connection.run_sync(lambda sync: run_migration(sync, "upgrade"))

    async with postgres_engine.connect() as connection:
        columns = await connection.run_sync(lambda sync: inspect(sync).get_columns("membership_renewal_deliveries"))
    assert next(column for column in columns if column["name"] == "previous_membership_id")["nullable"]
    saved = await receipts(postgres_engine)
    assert set(saved) == {
        (1, "START"), (1, "END"), (2, "START"), (3, "START"), (3, "END"),
        (8, "END"), (10, "START"), (10, "END"),
    }
    assert saved[1, "START"].previous_membership_id is None
    assert saved[1, "START"].activated and not saved[1, "START"].completed
    assert set(json.loads(saved[1, "START"].role_ids_to_add_json)) == {VIP, BADGE}
    assert json.loads(saved[1, "END"].role_ids_to_remove_json) == [VIP]
    assert saved[1, "END"].actor_id == "0"
    assert not saved[1, "END"].activated
    assert saved[8, "END"].previous_membership_id is None
    assert json.loads(saved[8, "END"].role_ids_to_remove_json) == [VIP]
    assert saved[10, "START"].completed and saved[10, "START"].actor_id == GUILD

    async with AsyncSession(postgres_engine) as session:
        members = (await session.exec(select(Membership))).all()
        assert len(members) == 11
        assert not (await session.get(Membership, 8)).is_active
        assert (await session.get(Membership, 3)).is_scheduled

    async with postgres_engine.begin() as connection:
        await connection.run_sync(lambda sync: run_migration(sync, "upgrade"))
    repeated = await receipts(postgres_engine)
    assert {key: row.id for key, row in repeated.items()} == {key: row.id for key, row in saved.items()}


@pytest.mark.asyncio
async def test_downgrade_preserves_memberships_and_renewal_history(postgres_engine):
    await seed_previous_schema(postgres_engine)
    async with postgres_engine.begin() as connection:
        await connection.run_sync(lambda sync: run_migration(sync, "upgrade"))
        await connection.run_sync(lambda sync: run_migration(sync, "downgrade"))
        columns = await connection.run_sync(lambda sync: inspect(sync).get_columns("membership_renewal_deliveries"))
    assert not next(column for column in columns if column["name"] == "previous_membership_id")["nullable"]
    saved = await receipts(postgres_engine)
    assert set(saved) == {(3, "START"), (3, "END"), (10, "START"), (10, "END")}
    assert saved[10, "START"].completed
    async with AsyncSession(postgres_engine) as session:
        assert len((await session.exec(select(Membership))).all()) == 11
