"""Opt-in row-lock regressions against an empty, disposable PostgreSQL database.

Set MEMBERSHIP_POSTGRES_TEST_URL to a postgresql+asyncpg URL whose database is
named matefield_membership_regression_<suffix>. The caller creates and drops that
database; this module only creates and removes its test tables. External Discord
and Warcon operations are mocked.
"""
import asyncio
import os
import re
import socket
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.modules.v1.services.memberships_service import MembershipsService
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import AddMembershipRequest, MembershipWarconDelivery


TEMPORARY_DATABASE = re.compile(r"matefield_membership_regression_[a-z0-9_]{8,48}\Z")
STEAM_A = "76561198000000011"
STEAM_B = "76561198000000012"
GUILD_ID = "444444444444444444"
ACTOR_ID = "555555555555555555"
DISCORD_ROLE_ID = "333333333333333333"


@pytest_asyncio.fixture
async def postgres_engine(monkeypatch):
    target = os.environ.get("MEMBERSHIP_POSTGRES_TEST_URL")
    if not target:
        pytest.skip("Set MEMBERSHIP_POSTGRES_TEST_URL to run isolated PostgreSQL lock tests")
    url = make_url(target)
    if url.drivername != "postgresql+asyncpg" or not TEMPORARY_DATABASE.fullmatch(url.database or ""):
        pytest.fail("PostgreSQL lock tests require a disposable matefield_membership_regression_ database")
    port = url.port or 5432
    allowed_addresses = {result[4][0] for result in socket.getaddrinfo(url.host, port, type=socket.SOCK_STREAM)}
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def database_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in allowed_addresses or address[1] != port:
            raise AssertionError("PostgreSQL lock tests cannot contact external services")
        return original_connect(sock, address)

    def database_connect_ex(sock, address):
        if not isinstance(address, tuple) or address[0] not in allowed_addresses or address[1] != port:
            raise AssertionError("PostgreSQL lock tests cannot contact external services")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", database_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", database_connect_ex)
    engine = create_async_engine(url, isolation_level="READ COMMITTED", pool_size=5, max_overflow=0)
    created = False
    try:
        async with engine.begin() as connection:
            actual_database = (await connection.execute(text("SELECT current_database()"))).scalar_one()
            assert actual_database == url.database and TEMPORARY_DATABASE.fullmatch(actual_database)
            existing_tables = (await connection.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            ))).all()
            assert not existing_tables, "The disposable regression database must start empty"
            await connection.run_sync(SQLModel.metadata.create_all)
            created = True
        yield engine
    finally:
        try:
            if created:
                async with engine.begin() as connection:
                    actual_database = (await connection.execute(text("SELECT current_database()"))).scalar_one()
                    assert actual_database == url.database and TEMPORARY_DATABASE.fullmatch(actual_database)
                    await connection.run_sync(SQLModel.metadata.drop_all)
        finally:
            await engine.dispose()


@pytest.fixture
def isolated_warcon_settings(monkeypatch):
    settings = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    for key, value in {
        "WARCON_URL": "http://warcon.test", "WARCON_API_TOKEN": "test-only",
        "WARCON_ORG_ID": "test-org", "WARCON_SERVER_ID": "test-server",
    }.items():
        monkeypatch.setattr(settings, key, value)


async def seed_catalog(engine, quota=None):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        role = Role(code="VIP", name="VIP", role_type="VIP", discord_role_id="333333333333333333")
        session.add_all([
            role,
            Player(steam_id=STEAM_A, discord_id="111111111111111111"),
            Player(steam_id=STEAM_B, discord_id="222222222222222222"),
        ])
        await session.flush()
        session.add_all([
            MembershipType(code="regular", name="VIP Normal", default_days=30, max_quota=quota, role_id=role.id),
            MembershipType(code="express", name="VIP Express", default_days=14, role_id=role.id),
        ])
        await session.commit()


def request(steam_id, code, operation):
    return AddMembershipRequest(steam_id=steam_id, membership_type=code, source="DISCORD", operation_id=operation)


def delivered():
    return MembershipWarconDelivery(status="SUCCESS", server_id="test-server", entry_id="test-entry")


async def backend_pid(session):
    return (await session.exec(text("SELECT pg_backend_pid()"))).scalar_one()


async def assert_database_lock(engine, waiting_pid, blocker_pid):
    """Observe the actual database lock, rather than infer it from a slow task."""
    async with engine.connect() as connection:
        async with asyncio.timeout(5):
            while True:
                blockers = (await connection.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting_pid}
                )).scalar_one()
                if blocker_pid in blockers:
                    return
                await asyncio.sleep(0.02)


async def stop_tasks(*tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_last_quota_serializes_different_players(postgres_engine, isolated_warcon_settings, monkeypatch):
    await seed_catalog(postgres_engine, quota=1)
    before_commit = asyncio.Event()
    release_commit = asyncio.Event()
    deliveries = []

    class PausedCommitSession(AsyncSession):
        async def commit(self):
            if not before_commit.is_set():
                before_commit.set()
                await release_commit.wait()
            await super().commit()

    async def mock_delivery(_client, steam_id, membership_id, membership_type, expiry):
        deliveries.append(steam_id)
        return delivered()

    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", mock_delivery)
    async with PausedCommitSession(postgres_engine, expire_on_commit=False) as first_session, \
            AsyncSession(postgres_engine, expire_on_commit=False) as second_session:
        first_pid = await backend_pid(first_session)
        second_pid = await backend_pid(second_session)
        first = asyncio.create_task(MembershipsService.add_membership(
            request(STEAM_A, "regular", "quota-first"), first_session
        ))
        second = None
        try:
            async with asyncio.timeout(10):
                await before_commit.wait()
                second = asyncio.create_task(MembershipsService.add_membership(
                    request(STEAM_B, "regular", "quota-second"), second_session
                ))
                await assert_database_lock(postgres_engine, second_pid, first_pid)
                assert not second.done()
                release_commit.set()
                assert (await first).ok is True
                with pytest.raises(HTTPException) as rejected:
                    await second
                assert rejected.value.status_code == 400
                assert "cupos" in rejected.value.detail
        finally:
            release_commit.set()
            await stop_tasks(*[task for task in (first, second) if task is not None])

    async with AsyncSession(postgres_engine) as session:
        count = (await session.exec(select(func.count(Membership.id)))).one()
        assert count == 1
        assert (await session.exec(select(Membership.steam_id))).one() == STEAM_A
    assert deliveries == [STEAM_A]


@pytest.mark.asyncio
async def test_warcon_delivery_serializes_before_later_membership(postgres_engine, isolated_warcon_settings, monkeypatch):
    await seed_catalog(postgres_engine)
    first_delivery_started = asyncio.Event()
    release_delivery = asyncio.Event()
    expiries_applied = []
    first_delivery_pid = None
    before = datetime.now(timezone.utc)

    async with AsyncSession(postgres_engine, expire_on_commit=False) as first_session, \
            AsyncSession(postgres_engine, expire_on_commit=False) as second_session:
        second_pid = await backend_pid(second_session)

        async def mock_delivery(_client, steam_id, membership_id, membership_type, expiry):
            nonlocal first_delivery_pid
            if membership_type == "express":
                first_delivery_pid = await backend_pid(first_session)
                first_delivery_started.set()
                await release_delivery.wait()
            expiries_applied.append(expiry)
            return delivered()

        monkeypatch.setattr(WarconClient, "upsert_reserved_slot", mock_delivery)
        first = asyncio.create_task(MembershipsService.add_membership(
            request(STEAM_A, "express", "delivery-first"), first_session
        ))
        second = None
        try:
            async with asyncio.timeout(10):
                await first_delivery_started.wait()
                second = asyncio.create_task(MembershipsService.add_membership(
                    request(STEAM_A, "regular", "delivery-second"), second_session
                ))
                await assert_database_lock(postgres_engine, second_pid, first_delivery_pid)
                assert not second.done()
                assert expiries_applied == []
                release_delivery.set()
                assert (await first).ok is True
                assert (await second).ok is True
        finally:
            release_delivery.set()
            await stop_tasks(*[task for task in (first, second) if task is not None])

    assert len(expiries_applied) == 2
    assert 13.9 < (expiries_applied[0] - before).total_seconds() / 86400 < 14.1
    assert 29.9 < (expiries_applied[1] - before).total_seconds() / 86400 < 30.1
    assert expiries_applied[1] > expiries_applied[0]
    async with AsyncSession(postgres_engine) as session:
        assert (await session.exec(select(func.count(Membership.id)))).one() == 2


@pytest.fixture
def isolated_guild_settings(monkeypatch):
    settings = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS
    monkeypatch.setattr(settings, "DISCORD_GUILD_IDS", GUILD_ID)
    monkeypatch.setattr(settings, "DISCORD_GUILD_ID", None)


@pytest.fixture
def warcon_deliveries(monkeypatch):
    deliveries = []

    async def mock_delivery(_client, steam_id, membership_id, membership_type, expiry):
        deliveries.append(steam_id)
        return delivered()

    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", mock_delivery)
    return deliveries


async def seed_scoped_catalog(engine):
    """Keep one type per logical role so shared-role validation cannot mask races."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        role = Role(code="VIP", name="VIP", role_type="VIP", discord_role_id=DISCORD_ROLE_ID)
        session.add_all([
            role,
            Player(steam_id=STEAM_A, discord_id="111111111111111111"),
            Player(steam_id=STEAM_B, discord_id="222222222222222222"),
        ])
        await session.flush()
        session.add_all([
            MembershipType(code="regular", name="VIP Normal", default_days=30, role_id=role.id),
            RoleDiscordBinding(role_id=role.id, guild_id=GUILD_ID,
                               discord_role_id=DISCORD_ROLE_ID, configured_by=ACTOR_ID),
        ])
        await session.commit()


def unassign_request():
    # Opt-in tests remain collectable while the DELETE implementation is developed.
    from wardogs_schemas.dtos import UnassignMembershipRoleRequest
    return UnassignMembershipRoleRequest(actor_id=ACTOR_ID)


def scoped_request(operation):
    return request(STEAM_A, "regular", operation).model_copy(update={"guild_id": GUILD_ID})


def paused_commit_session(before_commit, release_commit):
    class PausedCommitSession(AsyncSession):
        async def commit(self):
            if not before_commit.is_set():
                before_commit.set()
                await release_commit.wait()
            await super().commit()

    return PausedCommitSession


@pytest.mark.asyncio
async def test_unassign_waits_for_creation_then_preserves_active_binding(
    postgres_engine, isolated_warcon_settings, isolated_guild_settings, warcon_deliveries,
):
    await seed_scoped_catalog(postgres_engine)
    before_commit, release_commit = asyncio.Event(), asyncio.Event()
    PausedCommitSession = paused_commit_session(before_commit, release_commit)

    async with PausedCommitSession(postgres_engine, expire_on_commit=False) as creation_session, \
            AsyncSession(postgres_engine, expire_on_commit=False) as deletion_session:
        creation_pid = await backend_pid(creation_session)
        deletion_pid = await backend_pid(deletion_session)
        creation = asyncio.create_task(MembershipsService.add_membership(
            scoped_request("creation-before-unassign"), creation_session
        ))
        deletion = None
        try:
            async with asyncio.timeout(10):
                await before_commit.wait()
                deletion = asyncio.create_task(MembershipRolesService.unassign(
                    GUILD_ID, "regular", unassign_request(), deletion_session
                ))
                await assert_database_lock(postgres_engine, deletion_pid, creation_pid)
                assert not deletion.done()
                release_commit.set()
                assert (await creation).ok is True
                with pytest.raises(HTTPException) as rejected:
                    await deletion
                assert rejected.value.status_code == 409
                assert rejected.value.detail == {"code": "membership_role_in_use"}
        finally:
            release_commit.set()
            await stop_tasks(*[task for task in (creation, deletion) if task is not None])

    async with AsyncSession(postgres_engine) as session:
        binding = (await session.exec(select(RoleDiscordBinding))).one()
        assert binding.guild_id == GUILD_ID
        assert binding.discord_role_id == DISCORD_ROLE_ID
        assert (await session.exec(select(func.count(Membership.id)))).one() == 1
    assert warcon_deliveries == [STEAM_A]


@pytest.mark.asyncio
async def test_creation_waits_for_unassign_then_rejects_before_domain_or_warcon_write(
    postgres_engine, isolated_warcon_settings, isolated_guild_settings, warcon_deliveries,
):
    await seed_scoped_catalog(postgres_engine)
    before_commit, release_commit = asyncio.Event(), asyncio.Event()
    PausedCommitSession = paused_commit_session(before_commit, release_commit)

    async with PausedCommitSession(postgres_engine, expire_on_commit=False) as deletion_session, \
            AsyncSession(postgres_engine, expire_on_commit=False) as creation_session:
        deletion_pid = await backend_pid(deletion_session)
        creation_pid = await backend_pid(creation_session)
        deletion = asyncio.create_task(MembershipRolesService.unassign(
            GUILD_ID, "regular", unassign_request(), deletion_session
        ))
        creation = None
        try:
            async with asyncio.timeout(10):
                await before_commit.wait()
                creation = asyncio.create_task(MembershipsService.add_membership(
                    scoped_request("unassign-before-creation"), creation_session
                ))
                await assert_database_lock(postgres_engine, creation_pid, deletion_pid)
                assert not creation.done()
                release_commit.set()
                removed = await deletion
                assert removed.changed is True
                assert removed.discord_role_id == DISCORD_ROLE_ID
                with pytest.raises(HTTPException) as rejected:
                    await creation
                assert rejected.value.status_code == 409
                assert "Falta configurar" in rejected.value.detail
        finally:
            release_commit.set()
            await stop_tasks(*[task for task in (deletion, creation) if task is not None])

    async with AsyncSession(postgres_engine) as session:
        assert (await session.exec(select(func.count(RoleDiscordBinding.id)))).one() == 0
        assert (await session.exec(select(func.count(Membership.id)))).one() == 0
        assert (await session.exec(select(func.count(PlayerRole.role_id)))).one() == 0
    assert warcon_deliveries == []


@pytest.mark.asyncio
async def test_repeated_unassign_serializes_to_one_change(
    postgres_engine, isolated_guild_settings, warcon_deliveries,
):
    await seed_scoped_catalog(postgres_engine)
    before_commit, release_commit = asyncio.Event(), asyncio.Event()
    PausedCommitSession = paused_commit_session(before_commit, release_commit)

    async with PausedCommitSession(postgres_engine, expire_on_commit=False) as first_session, \
            AsyncSession(postgres_engine, expire_on_commit=False) as second_session:
        first_pid = await backend_pid(first_session)
        second_pid = await backend_pid(second_session)
        first = asyncio.create_task(MembershipRolesService.unassign(
            GUILD_ID, "regular", unassign_request(), first_session
        ))
        second = None
        try:
            async with asyncio.timeout(10):
                await before_commit.wait()
                second = asyncio.create_task(MembershipRolesService.unassign(
                    GUILD_ID, "regular", unassign_request(), second_session
                ))
                await assert_database_lock(postgres_engine, second_pid, first_pid)
                assert not second.done()
                release_commit.set()
                removed, repeated = await first, await second
                assert removed.changed is True
                assert removed.discord_role_id == DISCORD_ROLE_ID
                assert repeated.changed is False
                assert repeated.discord_role_id is None
                assert removed.actor_id == repeated.actor_id == ACTOR_ID
        finally:
            release_commit.set()
            await stop_tasks(*[task for task in (first, second) if task is not None])

    async with AsyncSession(postgres_engine) as session:
        assert (await session.exec(select(func.count(RoleDiscordBinding.id)))).one() == 0
        assert (await session.exec(select(func.count(Membership.id)))).one() == 0
    assert warcon_deliveries == []


@pytest.mark.asyncio
async def test_configure_waits_for_unassign_and_preserves_the_new_binding(
    postgres_engine, isolated_guild_settings, warcon_deliveries,
):
    from wardogs_schemas.dtos import ConfigureMembershipRoleRequest

    await seed_scoped_catalog(postgres_engine)
    before_commit, release_commit = asyncio.Event(), asyncio.Event()
    PausedCommitSession = paused_commit_session(before_commit, release_commit)
    replacement_role = "666666666666666666"

    async with PausedCommitSession(postgres_engine, expire_on_commit=False) as deletion_session, \
            AsyncSession(postgres_engine, expire_on_commit=False) as configuration_session:
        deletion_pid = await backend_pid(deletion_session)
        configuration_pid = await backend_pid(configuration_session)
        deletion = asyncio.create_task(MembershipRolesService.unassign(
            GUILD_ID, "regular", unassign_request(), deletion_session
        ))
        configuration = None
        try:
            async with asyncio.timeout(10):
                await before_commit.wait()
                configuration = asyncio.create_task(MembershipRolesService.configure(
                    GUILD_ID, "regular", ConfigureMembershipRoleRequest(
                        discord_role_id=replacement_role, actor_id=ACTOR_ID,
                    ), configuration_session,
                ))
                await assert_database_lock(postgres_engine, configuration_pid, deletion_pid)
                assert not configuration.done()
                release_commit.set()
                assert (await deletion).changed is True
                configured = await configuration
                assert configured.changed is True
                assert configured.discord_role_id == replacement_role
        finally:
            release_commit.set()
            await stop_tasks(*[task for task in (deletion, configuration) if task is not None])

    async with AsyncSession(postgres_engine) as session:
        binding = (await session.exec(select(RoleDiscordBinding))).one()
        assert binding.guild_id == GUILD_ID
        assert binding.discord_role_id == replacement_role
        assert (await session.exec(select(func.count(Membership.id)))).one() == 0
    assert warcon_deliveries == []
