"""Real PostgreSQL serialization and nonblocking polling for scheduled renewals."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from test_membership_concurrency_postgres import (
    postgres_engine, isolated_warcon_settings, assert_database_lock, backend_pid, stop_tasks, delivered,
)
from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipRenewalDelivery, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding
from src.modules.v1.services.membership_renewals_service import MembershipRenewalsService
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import RenewMembershipRequest

STEAM = "76561198000000093"
USER = "111111111111111113"
GUILD = "222222222222222224"
ACTOR = "333333333333333334"
OLD = "444444444444444447"
NEW = "444444444444444448"


@pytest.fixture
def enabled_renewal_guild(monkeypatch):
    monkeypatch.setattr(ENVIRONMENT_SETTINGS.SECURITY_SETTINGS, "DISCORD_GUILD_IDS", GUILD)


async def seed(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        old_role = Role(code="EXPRESS", name="VIP Express", role_type="VIP")
        new_role = Role(code="REGULAR", name="VIP Normal", role_type="VIP")
        session.add_all([old_role, new_role, Player(steam_id=STEAM, discord_id=USER)])
        await session.flush()
        session.add_all([
            MembershipType(code="express", name="VIP Express", default_days=14, role_id=old_role.id),
            MembershipType(code="regular", name="VIP Normal", default_days=30, role_id=new_role.id),
            RoleDiscordBinding(role_id=old_role.id, guild_id=GUILD, discord_role_id=OLD, configured_by=ACTOR),
            RoleDiscordBinding(role_id=new_role.id, guild_id=GUILD, discord_role_id=NEW, configured_by=ACTOR),
            PlayerRole(steam_id=STEAM, role_id=old_role.id),
            Membership(steam_id=STEAM, membership_type="express", role_granted_id=old_role.id,
                       end_time=datetime.now(timezone.utc) + timedelta(days=14), discord_guild_id=GUILD),
        ])
        await session.commit()


def request(operation):
    return RenewMembershipRequest(steam_id=STEAM, membership_type="regular", operation_id=operation, guild_id=GUILD, actor_id=ACTOR)


@pytest.mark.asyncio
async def test_concurrent_renewals_serialize_and_only_one_future_period_is_saved(postgres_engine, isolated_warcon_settings, enabled_renewal_guild, monkeypatch):
    await seed(postgres_engine)
    delivery_started, release = asyncio.Event(), asyncio.Event()
    first_pid = None
    async with AsyncSession(postgres_engine, expire_on_commit=False) as first_session, AsyncSession(postgres_engine, expire_on_commit=False) as second_session:
        second_pid = await backend_pid(second_session)
        async def pause(_client, *args):
            nonlocal first_pid
            first_pid = await backend_pid(first_session)
            delivery_started.set()
            await release.wait()
            return delivered()
        monkeypatch.setattr(WarconClient, "upsert_reserved_slot", pause)
        first = asyncio.create_task(MembershipRenewalsService.renew(request("first"), first_session))
        second = None
        try:
            async with asyncio.timeout(10):
                await delivery_started.wait()
                second = asyncio.create_task(MembershipRenewalsService.renew(request("second"), second_session))
                await assert_database_lock(postgres_engine, second_pid, first_pid)
                assert not second.done()
                release.set()
                assert (await first).ok is True
                with pytest.raises(HTTPException) as rejected:
                    await second
                assert rejected.value.detail == {"code": "membership_renewal_already_scheduled"}
        finally:
            release.set()
            await stop_tasks(*[task for task in (first, second) if task is not None])
    async with AsyncSession(postgres_engine) as session:
        assert len((await session.exec(select(Membership))).all()) == 2
        assert len((await session.exec(select(MembershipRenewalDelivery))).all()) == 2


@pytest.mark.asyncio
async def test_poll_skips_warcon_player_lock_and_delivers_next_poll(postgres_engine, isolated_warcon_settings, enabled_renewal_guild, monkeypatch):
    await seed(postgres_engine)
    async def success(_client, *args):
        return delivered()
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", success)
    async with AsyncSession(postgres_engine, expire_on_commit=False) as session:
        result = await MembershipRenewalsService.renew(request("scheduled"), session)
        future = await session.get(Membership, result.membership.id)
        current = await session.get(Membership, result.previous_membership_id)
        now = datetime.now(timezone.utc)
        current.end_time = now - timedelta(seconds=1)
        future.start_time = current.end_time
        receipt = (await session.exec(select(MembershipRenewalDelivery).where(MembershipRenewalDelivery.phase == "START"))).one()
        receipt.available_at = current.end_time
        session.add_all([current, future, receipt])
        await session.commit()
    started, release = asyncio.Event(), asyncio.Event()
    async def pause(_client, *args):
        started.set()
        await release.wait()
        return delivered()
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", pause)
    async with AsyncSession(postgres_engine, expire_on_commit=False) as retry_session, AsyncSession(postgres_engine, expire_on_commit=False) as poll_session:
        future = await retry_session.get(Membership, result.membership.id)
        receipt = (await retry_session.exec(select(MembershipRenewalDelivery).where(MembershipRenewalDelivery.phase == "START"))).one()
        retry = asyncio.create_task(MembershipRenewalsService._deliver(future, receipt, None, retry_session, replayed=True))
        try:
            async with asyncio.timeout(10):
                await started.wait()
                polled = await asyncio.wait_for(MembershipRenewalsService.deliveries(GUILD, poll_session), timeout=1)
                assert polled.deliveries == []
                release.set()
                await retry
                polled = await MembershipRenewalsService.deliveries(GUILD, poll_session)
                assert len(polled.deliveries) == 1
                assert polled.deliveries[0].role_ids_to_add == [NEW]
                assert polled.deliveries[0].role_ids_to_remove == [OLD]
        finally:
            release.set()
            await stop_tasks(retry)
