import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import Player, PlayerRole, Role, RoleType


@pytest.mark.asyncio
async def test_get_player_active_role(client: AsyncClient, session: AsyncSession):
    # Arrange
    player = Player(steam_id="steam_admin", discord_id="discord_admin")
    role_admin = Role(code="SUPERADMIN", name="Super Admin", role_type=RoleType.SYSTEM)
    session.add(player)
    session.add(role_admin)
    await session.commit()
    await session.refresh(role_admin)
    assert role_admin.id is not None
    player_role = PlayerRole(steam_id="steam_admin", role_id=role_admin.id)
    session.add(player_role)
    await session.commit()

    # Act
    response = await client.get("/api/v1/db/players/steam/steam_admin")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["active_role"] == "ADMIN"  # Fallback mapped logical role


@pytest.mark.asyncio
async def test_role_register_and_assign(client: AsyncClient, session: AsyncSession):
    # Test new role registration endpoint
    player = Player(steam_id="steam_test1")
    session.add(player)
    await session.commit()

    # Register Role
    reg_resp = await client.post("/api/v1/db/roles", json={
        "code": "TEST_VIP",
        "name": "Test VIP",
        "role_type": "VIP",
        "discord_role_id": "111222"
    })
    assert reg_resp.status_code == 200

    # Assign Role
    assign_resp = await client.post("/api/v1/db/players/steam_test1/roles/TEST_VIP")
    assert assign_resp.status_code == 200

    # Verify Assignment
    get_resp = await client.get("/api/v1/db/players/steam/steam_test1")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["active_role"] == "VIP"
