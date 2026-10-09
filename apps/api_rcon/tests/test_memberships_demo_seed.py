from collections import Counter
from datetime import datetime, timedelta, timezone
import socket

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from src.connections.databases.db import Membership, MembershipType, Player, PlayerRole, RconServer, Role
from src.seeds.memberships_demo import main, seed_memberships, validate_local_target


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def reject_connection(*args, **kwargs):
        raise AssertionError("Demo tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    monkeypatch.setattr(socket, "create_connection", reject_connection)


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@pytest.mark.asyncio
async def test_creates_35_fictional_memberships_and_four_types(session):
    result = await seed_memberships(session, NOW)
    assert result == {
        "types_created": 4,
        "players_created": 35,
        "memberships_created": 35,
        "memberships_existing": 0,
    }
    types = (await session.exec(select(MembershipType))).all()
    assert {item.code: item.default_days for item in types} == {
        "express": 14, "regular": 30, "permanent": 0, "seed": 15,
    }
    assert {item.code: (item.name, item.price_usd, item.price_ars) for item in types} == {
        "express": ("VIP EXPRESS", 300, 500000),
        "regular": ("VIP NORMAL", 500, 700000),
        "permanent": ("VIP Permanente", 0, None),
        "seed": ("VIP por seeding", 0, None),
    }
    members = (await session.exec(select(Membership))).all()
    players = (await session.exec(select(Player))).all()
    assert len(players) == len(members) == 35
    assert Counter(item.membership_type for item in members) == {
        "express": 10, "regular": 10, "permanent": 5, "seed": 10,
    }
    assert sum(item.is_active for item in members) == 15
    assert sum(item.is_booster for item in members) == 11
    assert len({item.steam_id for item in members}) == 35
    assert len({item.start_time for item in members}) == 35
    assert all(item.steam_id.startswith("demo-") and item.discord_id is None for item in players)
    for member in members:
        assert member.role_granted_id is member.special_role_id is member.server_id is None
        assert member.rcon_sync_status == "PENDING"
        assert member.payment_source == ("REWARDS" if member.membership_type == "seed" else "MANUAL")
        assert as_utc(member.start_time) <= NOW
        if member.membership_type == "permanent":
            assert member.end_time is None
        else:
            assert member.end_time - member.start_time == timedelta(
                days={"express": 14, "seed": 15, "regular": 30}[member.membership_type]
            )
            if member.is_active:
                assert as_utc(member.end_time) > NOW
    assert not (await session.exec(select(Role))).all()
    assert not (await session.exec(select(PlayerRole))).all()
    assert not (await session.exec(select(RconServer))).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("seed_code", ["seed", "SeEd", "VIP_SEED"])
async def test_reuses_catalog_codes_aliases_and_preserves_seed_one_day(session, seed_code):
    catalog = [
        MembershipType(code="EXPRESS", name="Custom Express", default_days=9, is_active=False),
        MembershipType(code="VIP_COMUN", name="Custom Regular", default_days=42, price_usd=650),
        MembershipType(code="VIP_PERMANENTE", name="Custom Permanent", default_days=0),
        MembershipType(code=seed_code, name="Custom Seed", default_days=1, price_usd=123),
    ]
    session.add_all(catalog)
    await session.commit()
    before = [item.model_dump() for item in catalog]
    result = await seed_memberships(session, NOW)
    assert result["types_created"] == 0
    assert [item.model_dump() for item in catalog] == before
    assert len((await session.exec(select(MembershipType))).all()) == 4
    members = (await session.exec(select(Membership))).all()
    assert len(members) == 35
    for member in members:
        assert as_utc(member.start_time) <= NOW
        if member.end_time is not None:
            days = next(item.default_days for item in catalog if item.code == member.membership_type)
            assert member.end_time - member.start_time == timedelta(days=days)
    seeds = [item for item in members if item.steam_id.startswith("demo-seed-")]
    assert len(seeds) == 10
    assert all(item.membership_type == seed_code for item in seeds)
    assert sum(item.is_active for item in members) == 15
    assert sum(item.is_booster for item in members) == 11


@pytest.mark.asyncio
async def test_repeated_seed_preserves_manual_edits_and_unrelated_records(session):
    await seed_memberships(session, NOW)
    regular = (await session.exec(select(MembershipType).where(MembershipType.code == "regular"))).one()
    demo = (await session.exec(select(Membership).where(Membership.steam_id == "demo-regular-01"))).one()
    player = await session.get(Player, demo.steam_id)
    regular.default_days = 42
    regular.name = "Edited regular"
    regular.is_active = False
    demo.membership_type = "custom-manual-type"
    demo.is_active = False
    demo.is_booster = True
    demo.start_time = NOW - timedelta(days=10)
    demo.end_time = NOW + timedelta(days=2)
    player.observations = "Keep this manual note"
    session.add_all([regular, demo, player, MembershipType(code="other", name="Other", default_days=60)])
    session.add(Player(steam_id="unrelated", observations="Preserve"))
    await session.flush()
    session.add(Membership(steam_id="unrelated", membership_type="other", is_active=False, start_time=NOW))
    await session.commit()
    members_before = {item.id: item.model_dump() for item in (await session.exec(select(Membership))).all()}
    players_before = {item.steam_id: item.model_dump() for item in (await session.exec(select(Player))).all()}
    types_before = {item.id: item.model_dump() for item in (await session.exec(select(MembershipType))).all()}

    for date in (NOW + timedelta(days=1), NOW + timedelta(days=30)):
        result = await seed_memberships(session, date)
        assert result == {
            "types_created": 0,
            "players_created": 0,
            "memberships_created": 0,
            "memberships_existing": 35,
        }
        assert {item.id: item.model_dump() for item in (await session.exec(select(Membership))).all()} == members_before
        assert {item.steam_id: item.model_dump() for item in (await session.exec(select(Player))).all()} == players_before
        assert {item.id: item.model_dump() for item in (await session.exec(select(MembershipType))).all()} == types_before


@pytest.mark.asyncio
@pytest.mark.parametrize("is_active", [True, False])
async def test_refuses_active_rcon_servers_before_creating_fixtures(session, is_active):
    session.add(RconServer(name="Fictional", ip="invalid.test", port=7776, password="fake", is_active=is_active))
    await session.commit()
    if is_active:
        with pytest.raises(RuntimeError, match="without active RCON servers"):
            await seed_memberships(session, NOW)
        assert not (await session.exec(select(Player))).all()
        assert not (await session.exec(select(Membership))).all()
        assert not (await session.exec(select(MembershipType))).all()
    else:
        assert (await seed_memberships(session, NOW))["memberships_created"] == 35


@pytest.mark.asyncio
async def test_rolls_back_types_players_and_partial_memberships_on_failure(session):
    await session.exec(text(
        "CREATE TRIGGER reject_demo BEFORE INSERT ON memberships "
        "WHEN NEW.steam_id = 'demo-regular-01' "
        "BEGIN SELECT RAISE(ABORT, 'demo insertion failure'); END"
    ))
    await session.commit()
    with pytest.raises(IntegrityError, match="demo insertion failure"):
        await seed_memberships(session, NOW)
    assert not (await session.exec(select(Player))).all()
    assert not (await session.exec(select(Membership))).all()
    assert not (await session.exec(select(MembershipType))).all()
    await session.exec(text("DROP TRIGGER reject_demo"))
    await session.commit()
    assert (await seed_memberships(session, NOW))["memberships_created"] == 35


@pytest.mark.asyncio
async def test_existing_api_lists_demo_memberships_in_four_pages(client, session):
    await seed_memberships(session, NOW)
    pages = []
    for page in range(1, 6):
        response = await client.get(f"/api/v1/db/memberships?page={page}&limit=10")
        assert response.status_code == 200
        payload = response.json()
        assert payload["page"] == page
        assert payload["limit"] == 10
        assert payload["total"] == 35
        pages.append(payload["memberships"])
    assert [len(page) for page in pages] == [10, 10, 10, 5, 0]
    listed = [member for page in pages for member in page]
    database_ids = {item.id for item in (await session.exec(select(Membership))).all()}
    assert len({item["id"] for item in listed}) == 35
    assert {item["id"] for item in listed} == database_ids
    assert all(item["end_date"] is None for item in listed if item["type"] == "permanent")


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", [None, "production", "staging"])
async def test_cli_requires_explicit_local_environment(monkeypatch, environment):
    if environment is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", environment)
    with pytest.raises(RuntimeError, match="APP_ENV=local, test or dev explicitly"):
        await main()


@pytest.mark.parametrize("environment", ["local", "test", "dev"])
@pytest.mark.parametrize("database_host,rcon_host", [
    ("postgres", "mock_rcon"),
    ("matefield_db_local", "mock_rcon_1"),
    ("localhost", "127.0.0.1"),
    ("127.0.0.1", "mock-rcon"),
])
def test_cli_accepts_only_explicit_local_destinations(environment, database_host, rcon_host):
    validate_local_target(
        environment,
        f"postgresql+asyncpg://demo:fake@{database_host}:5432/demo",
        f"http://{rcon_host}:7776",
    )


@pytest.mark.parametrize("database_host,rcon_host,error", [
    ("database.invalid", "mock_rcon", "local database host"),
    ("postgres", "game.invalid", "mock or loopback fallback"),
    ("postgres", "mock_rcon.example.invalid", "mock or loopback fallback"),
])
def test_cli_rejects_remote_destinations_without_printing_credentials(database_host, rcon_host, error):
    with pytest.raises(RuntimeError, match=error) as caught:
        validate_local_target(
            "local",
            f"postgresql+asyncpg://demo:must-not-print@{database_host}:5432/demo",
            f"http://{rcon_host}:7776",
        )
    assert "must-not-print" not in str(caught.value)
    assert database_host not in str(caught.value)
    assert rcon_host not in str(caught.value)
