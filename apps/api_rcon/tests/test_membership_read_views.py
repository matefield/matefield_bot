"""Membership reads enrich identities in batches without delivering any benefits."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from wardogs_config import ENVIRONMENT_SETTINGS

GUILD = "111111111111111111"
OTHER_GUILD = "222222222222222222"
USER = "333333333333333333"
OTHER_USER = "444444444444444444"
DISCORD_ROLE = "555555555555555555"
GLOBAL_ROLE = "666666666666666666"
STEAM = "76561198000000001"
OTHER_STEAM = "76561198000000002"
START = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
END = datetime(2026, 1, 16, 3, 4, 5, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def read_environment(monkeypatch):
    monkeypatch.setattr(ENVIRONMENT_SETTINGS.SECURITY_SETTINGS, "DISCORD_GUILD_IDS", f"{GUILD},{OTHER_GUILD}")
    monkeypatch.setattr(ENVIRONMENT_SETTINGS.SECURITY_SETTINGS, "DISCORD_GUILD_ID", None)


async def seed(session, count=1):
    role = Role(code="VIP", name="VIP", role_type="VIP", discord_role_id=GLOBAL_ROLE)
    session.add(role)
    await session.flush()
    m_type = MembershipType(code="express", name="VIP Express", default_days=14, role_id=role.id)
    session.add_all([m_type, RoleDiscordBinding(guild_id=GUILD, role_id=role.id,
                                             discord_role_id=DISCORD_ROLE, configured_by=USER)])
    memberships = []
    for index in range(count):
        steam_id = str(int(STEAM) + index)
        discord_id = str(int(USER) + index)
        session.add(Player(steam_id=steam_id, discord_id=discord_id))
        memberships.append(Membership(steam_id=steam_id, membership_type="ExPrEsS",
                                      role_granted_id=role.id, start_time=START, end_time=END,
                                      rcon_sync_status="FAILED"))
    session.add_all(memberships)
    await session.commit()
    return memberships


@pytest.mark.asyncio
async def test_list_enriches_linked_id_and_human_type_while_preserving_iso_dates(client, session, monkeypatch):
    membership = (await seed(session))[0]
    delivery = AsyncMock()
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", delivery)
    commit = AsyncMock(wraps=session.commit)
    monkeypatch.setattr(session, "commit", commit)
    response = await client.get(f"/api/v1/db/memberships?guild_id={GUILD}")
    assert response.status_code == 200
    row = response.json()["memberships"][0]
    assert row["id"] == membership.id
    assert row["steam_id"] == STEAM
    assert row["discord_id"] == USER
    assert row["type"] == "ExPrEsS"
    assert row["type_name"] == "VIP Express"
    assert datetime.fromisoformat(row["start_date"]).replace(tzinfo=timezone.utc) == START
    assert datetime.fromisoformat(row["end_date"]).replace(tzinfo=timezone.utc) == END
    assert row["role_granted_discord_id"] == DISCORD_ROLE
    assert row["rcon_sync_status"] == "FAILED"
    assert membership.is_active is True
    assert (await session.exec(select(PlayerRole))).all() == []
    commit.assert_not_awaited()
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_historical_type_without_catalog_and_unlinked_player_remain_readable(client, session):
    session.add(Player(steam_id=STEAM))
    session.add(Membership(steam_id=STEAM, membership_type="LEGACY", start_time=START,
                           end_time=None, is_active=False))
    await session.commit()
    response = await client.get(f"/api/v1/db/memberships?guild_id={GUILD}")
    assert response.status_code == 200
    row = response.json()["memberships"][0]
    assert row["discord_id"] is None
    assert row["type"] == "LEGACY"
    assert row["type_name"] is None
    assert row["role_granted_id"] is None
    assert row["role_granted_discord_id"] is None
    assert row["end_date"] is None
    assert row["is_active"] is False


@pytest.mark.asyncio
async def test_user_filter_does_not_expose_other_players_and_respects_guild_binding(client, session):
    memberships = await seed(session, count=2)
    response = await client.get(f"/api/v1/db/memberships?discord_id={USER}&guild_id={OTHER_GUILD}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [row["id"] for row in payload["memberships"]] == [memberships[0].id]
    assert payload["memberships"][0]["discord_id"] == USER
    # Never use the global role or another guild's binding in this guild.
    assert payload["memberships"][0]["role_granted_discord_id"] is None
    unknown = await client.get(f"/api/v1/db/memberships?discord_id=777777777777777777&guild_id={GUILD}")
    assert unknown.json() == {"page": 1, "limit": 10, "total": 0, "memberships": []}


@pytest.mark.asyncio
async def test_roleless_active_membership_does_not_run_delivery_resolution(client, session, monkeypatch):
    session.add_all([Player(steam_id=STEAM, discord_id=USER),
                     MembershipType(code="regular", name="VIP Normal"),
                     Membership(steam_id=STEAM, membership_type="regular", start_time=START)])
    await session.commit()
    resolution = AsyncMock(side_effect=AssertionError("Read paths must not resolve roles for delivery"))
    monkeypatch.setattr(MembershipRolesService, "resolve_roles", resolution)
    response = await client.get(f"/api/v1/db/memberships?discord_id={USER}&guild_id={GUILD}")
    assert response.status_code == 200
    row = response.json()["memberships"][0]
    assert row["is_active"] is True
    assert row["type_name"] == "VIP Normal"
    assert row["role_granted_id"] is None
    assert row["role_granted_discord_id"] is None
    resolution.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 25])
async def test_enrichment_uses_constant_number_of_reads_per_page(client, session, test_engine, count):
    memberships = await seed(session, count=count)
    statements = []

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        response = await client.get(f"/api/v1/db/memberships?guild_id={GUILD}&limit=25")
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record_sql)
    assert response.status_code == 200
    assert response.json()["total"] == count
    assert [row["id"] for row in response.json()["memberships"]] == sorted((row.id for row in memberships), reverse=True)
    assert len(statements) == 7  # Page, total, players, types, removal receipts, roles, guild bindings.
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


@pytest.mark.asyncio
async def test_user_view_prioritizes_current_memberships_over_expired_flags_and_history(client, session):
    session.add(Player(steam_id=STEAM, discord_id=USER))
    permanent = Membership(steam_id=STEAM, membership_type="PERMANENT", start_time=START,
                           end_time=None, is_active=True)
    expired_but_flagged_active = Membership(steam_id=STEAM, membership_type="EXPRESS", start_time=START,
                                           end_time=END, is_active=True)
    history = [Membership(steam_id=STEAM, membership_type="EXPRESS", start_time=datetime(2026, 2, day, tzinfo=timezone.utc),
                          end_time=None, is_active=False) for day in range(1, 13)]
    session.add_all([permanent, expired_but_flagged_active, *history])
    await session.commit()
    filtered = await client.get(f"/api/v1/db/memberships?discord_id={USER}&guild_id={GUILD}&limit=10")
    assert filtered.status_code == 200
    rows = filtered.json()["memberships"]
    assert filtered.json()["total"] == 14
    assert rows[0]["id"] == permanent.id and rows[0]["status"] == "ACTIVE"
    assert all(not row["is_active"] and row["status"] == "INACTIVE" for row in rows[1:])
    assert [row["id"] for row in rows[1:]] == sorted((row.id for row in history), reverse=True)[:9]
    last_page = await client.get(f"/api/v1/db/memberships?discord_id={USER}&guild_id={GUILD}&limit=10&page=2")
    expired = last_page.json()["memberships"][-1]
    assert expired["id"] == expired_but_flagged_active.id and expired["status"] == "EXPIRED"
    assert expired["is_active"] is True  # A read must not expire the persisted row.
    # The general list uses the same active-first order before pagination.
    general = await client.get(f"/api/v1/db/memberships?guild_id={GUILD}&limit=10")
    assert [row["id"] for row in general.json()["memberships"]] == [permanent.id, *sorted((row.id for row in history), reverse=True)[:9]]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["express", "ExPrEsS"])
async def test_catalog_name_equal_to_code_is_still_a_human_name(client, session, name):
    await seed(session)
    membership_type = (await session.exec(select(MembershipType).where(MembershipType.code == "express"))).one()
    membership_type.name = name
    session.add(membership_type)
    await session.commit()
    response = await client.get(f"/api/v1/db/memberships?guild_id={GUILD}")
    assert response.status_code == 200
    row = response.json()["memberships"][0]
    assert row["type"] == "ExPrEsS"
    assert row["type_name"] == name


@pytest.mark.asyncio
@pytest.mark.parametrize("personal", [False, True])
async def test_status_groups_are_ordered_before_pagination_without_writes_or_lost_periods(
    client, session, test_engine, monkeypatch, personal,
):
    from src.modules.v1.services import membership_state_service, memberships_service

    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(memberships_service, "datetime", FrozenDateTime)
    monkeypatch.setattr(membership_state_service, "datetime", FrozenDateTime)
    session.add(Player(steam_id=STEAM, discord_id=USER))
    active_old = Membership(steam_id=STEAM, membership_type="regular", is_active=True,
                            start_time=now - timedelta(days=300), end_time=now + timedelta(days=2))
    active_new = Membership(steam_id=STEAM, membership_type="regular", is_active=True,
                            start_time=now - timedelta(days=100), end_time=None)
    scheduled = Membership(steam_id=STEAM, membership_type="express", is_active=False, is_scheduled=True,
                           start_time=now + timedelta(days=100), end_time=now + timedelta(days=114))
    future = Membership(steam_id=STEAM, membership_type="express", is_active=True,
                        start_time=now + timedelta(days=10), end_time=now + timedelta(days=24))
    expired = Membership(steam_id=STEAM, membership_type="express", is_active=True,
                         start_time=now - timedelta(days=1), end_time=now - timedelta(hours=1))
    inactive = Membership(steam_id=STEAM, membership_type="express", is_active=False,
                          start_time=now - timedelta(hours=2), end_time=None)
    periods = [active_old, expired, scheduled, inactive, future, active_new]
    session.add_all(periods)
    await session.commit()
    expected = [active_new, active_old, scheduled, future, inactive, expired]
    statements = []

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    commit = AsyncMock(wraps=session.commit)
    monkeypatch.setattr(session, "commit", commit)
    delivery = AsyncMock(side_effect=AssertionError("A read must not deliver game benefits"))
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", delivery)
    event.listen(test_engine.sync_engine, "before_cursor_execute", record_sql)
    rows = []
    try:
        for page in range(1, 5):
            params = {"guild_id": GUILD, "limit": 2, "page": page}
            if personal:
                params["discord_id"] = USER
            response = await client.get("/api/v1/db/memberships", params=params)
            assert response.status_code == 200
            result = response.json()
            assert result["total"] == 6 and result["page"] == page and result["limit"] == 2
            assert [row["id"] for row in result["memberships"]] == [period.id for period in expected[(page - 1) * 2:page * 2]]
            rows.extend(result["memberships"])
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record_sql)
    assert [row["status"] for row in rows] == ["ACTIVE", "ACTIVE", "SCHEDULED", "NOT_STARTED", "INACTIVE", "EXPIRED"]
    assert len({row["id"] for row in rows}) == len(periods)
    assert {row["id"] for row in rows} == {period.id for period in periods}
    assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    commit.assert_not_awaited()
    delivery.assert_not_awaited()
    # Persisted flags stay untouched even when their dates describe an expired period.
    await session.refresh(expired)
    assert expired.is_active is True and expired.is_scheduled is False
