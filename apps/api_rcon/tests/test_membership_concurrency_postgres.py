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
from src.connections.databases.db import Membership, MembershipType, Player, Role
from src.modules.v1.services.memberships_service import MembershipsService
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import AddMembershipRequest, MembershipWarconDelivery


TEMPORARY_DATABASE = re.compile(r"matefield_membership_regression_[a-z0-9_]{8,48}\Z")
STEAM_A = "76561198000000011"
STEAM_B = "76561198000000012"


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
