from datetime import UTC, datetime, timedelta

import pytest
import src.connections.apis.rcon as rcon_module
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import BotConfig, Membership, Player, Role
from wardogs_schemas import v1 as schemas
from wardogs_config import ENVIRONMENT_SETTINGS


@pytest.fixture(autouse=True)
def mock_rcon(mocker, monkeypatch):
    # These tests exercise legacy direct RCON independently of the developer env.
    monkeypatch.setattr(ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS, "WARCON_URL", "")
    # Mock the default RCON client used in endpoints
    mocker.patch.object(rcon_module.rcon_client, 'get_reserved_slots', return_value=schemas.ReservedSlots(reservedSlots=[]))
    mocker.patch.object(rcon_module.rcon_client, 'sync_reserved_slots', return_value=None)


@pytest.mark.asyncio
async def test_sync_expires_old_memberships(client: AsyncClient, session: AsyncSession):
    now = datetime.now(UTC)
    p = Player(steam_id="123", discord_id="456")
    m = Membership(
        steam_id="123",
        membership_type="VIP_EXPRESS",
        is_active=True,
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=1)
    )
    session.add(p)
    session.add(m)
    await session.commit()

    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    await session.refresh(m)
    assert m.is_active is False

    data = response.json()
    assert data["sync_data"] == [{"discord_id": "456", "active_memberships": [], "special_roles": []}]


@pytest.mark.asyncio
async def test_sync_adds_authorized_slots(client: AsyncClient, session: AsyncSession, mocker):
    mock_add = mocker.patch.object(rcon_module.rcon_client, 'sync_reserved_slots')

    now = datetime.now(UTC)
    p = Player(steam_id="VALID_STEAM_ID", discord_id="456")
    m = Membership(
        steam_id="VALID_STEAM_ID",
        membership_type="VIP_EXPRESS",
        is_active=True,
        start_time=now - timedelta(days=2),
        end_time=now + timedelta(days=1)
    )
    session.add(p)
    session.add(m)
    await session.commit()

    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    mock_add.assert_called_once()


@pytest.mark.asyncio
async def test_sync_removes_unauthorized_slots(client: AsyncClient, session: AsyncSession, mocker):
    mocker.patch.object(rcon_module.rcon_client, 'get_reserved_slots',
                        return_value=schemas.ReservedSlots(reservedSlots=["UNAUTHORIZED_STEAM"]))
    mock_remove = mocker.patch.object(rcon_module.rcon_client, 'sync_reserved_slots')

    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    mock_remove.assert_called_once()


@pytest.mark.asyncio
async def test_sync_returns_discord_mappings(client: AsyncClient, session: AsyncSession):
    role = Role(code="VIP_EXPRESS", name="VIP Express", role_type="VIP", discord_role_id="999888777")
    session.add(role)
    await session.commit()

    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    data = response.json()
    assert "role_maps" in data
    assert data["role_maps"]["VIP_EXPRESS"] == 999888777


@pytest.mark.asyncio
async def test_sync_permanent_memberships(client: AsyncClient, session: AsyncSession, mocker):
    mock_add = mocker.patch.object(rcon_module.rcon_client, 'sync_reserved_slots')

    now = datetime.now(UTC)
    p = Player(steam_id="PERM_STEAM_ID", discord_id="456")
    m = Membership(
        steam_id="PERM_STEAM_ID",
        membership_type="VIP_FUNDADOR",
        is_active=True,
        start_time=now - timedelta(days=2),
        end_time=None
    )
    session.add(p)
    session.add(m)
    await session.commit()

    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    await session.refresh(m)
    assert m.is_active is True  # Permanent memberships do not expire
    mock_add.assert_called_once()


@pytest.mark.asyncio
async def test_sync_keeps_active_membership_in_sync_data(client: AsyncClient, session: AsyncSession):
    now = datetime.now(UTC)
    p = Player(steam_id="EXISTING_VIP_STEAM", discord_id="111222333")
    m = Membership(
        steam_id="EXISTING_VIP_STEAM",
        membership_type="VIP_EXPRESS",
        is_active=True,
        start_time=now - timedelta(days=5),
        end_time=now + timedelta(days=25)
    )
    role = Role(code="VIP_EXPRESS", name="VIP Express", role_type="VIP", discord_role_id="999888777")
    session.add(p)
    session.add(m)
    session.add(role)
    await session.commit()

    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    data = response.json()
    user_entry = next((u for u in data["sync_data"] if u["discord_id"] == "111222333"), None)
    assert user_entry is not None
    assert "VIP_EXPRESS" in user_entry["active_memberships"]
    assert data["role_maps"]["VIP_EXPRESS"] == 999888777


@pytest.mark.asyncio
async def test_sync_only_removes_role_when_all_memberships_expire(client: AsyncClient, session: AsyncSession):
    now = datetime.now(UTC)
    p = Player(steam_id="MULTI_VIP_STEAM", discord_id="444555666")
    m_expired = Membership(
        steam_id="MULTI_VIP_STEAM",
        membership_type="VIP_MVP_GIFT",
        is_active=True,
        start_time=now - timedelta(days=10),
        end_time=now - timedelta(days=1)
    )
    m_active = Membership(
        steam_id="MULTI_VIP_STEAM",
        membership_type="VIP_EXPRESS",
        is_active=True,
        start_time=now - timedelta(days=2),
        end_time=now + timedelta(days=28)
    )
    config1 = BotConfig(config_key="ROLE_MAP_VIP_EXPRESS", config_value="999888777")
    config2 = BotConfig(config_key="ROLE_MAP_VIP_MVP_GIFT", config_value="111222333")
    session.add(p)
    session.add(m_expired)
    session.add(m_active)
    session.add(config1)
    session.add(config2)
    await session.commit()

    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    data = response.json()
    user_entry = next((u for u in data["sync_data"] if u["discord_id"] == "444555666"), None)
    assert user_entry is not None

    await session.refresh(m_expired)
    assert m_expired.is_active is False

    await session.refresh(m_active)
    assert m_active.is_active is True

    assert "VIP_EXPRESS" in user_entry["active_memberships"]
    assert "VIP_MVP_GIFT" not in user_entry["active_memberships"]


@pytest.mark.asyncio
async def test_sync_preserves_special_role_on_expiration(client: AsyncClient, session: AsyncSession):
    from sqlmodel import select
    from src.connections.databases.db import PlayerRole

    now = datetime.now(UTC)
    p = Player(steam_id="ROLE_EXPIRE_STEAM", discord_id="777888999")
    r = Role(code="CUSTOM_VIP", name="Custom VIP", role_type="SPECIAL", discord_role_id="111999")
    session.add_all([p, r])
    await session.commit()
    await session.refresh(r)
    assert r.id is not None

    pr = PlayerRole(steam_id="ROLE_EXPIRE_STEAM", role_id=r.id)
    m = Membership(
        steam_id="ROLE_EXPIRE_STEAM",
        membership_type="VIP_CUSTOM",
        special_role_id=r.id,
        is_active=True,
        start_time=now - timedelta(days=35),
        end_time=now - timedelta(days=5)
    )
    session.add_all([pr, m])
    await session.commit()

    # Pre-condition: player has PlayerRole
    active_pr = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "ROLE_EXPIRE_STEAM"))).first()
    assert active_pr is not None

    # Sync
    response = await client.post("/api/v1/db/sync_memberships")
    assert response.status_code == 200

    # Post-condition: membership expired, but special role is PERMANENT and preserved
    await session.refresh(m)
    assert m.is_active is False

    preserved_pr = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "ROLE_EXPIRE_STEAM"))).first()
    assert preserved_pr is not None


