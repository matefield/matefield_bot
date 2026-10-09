from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import (
    Membership,
    MembershipType,
    Player,
    PlayerRole,
    Role,
)


@pytest.mark.asyncio
async def test_edit_membership(client: AsyncClient, session: AsyncSession):
    now = datetime.now(UTC)
    p = Player(steam_id="123")
    m = Membership(
        steam_id="123",
        membership_type="VIP_EXPRESS",
        is_active=True,
        start_time=now - timedelta(days=2),
        end_time=now + timedelta(days=5)
    )
    session.add(p)
    session.add(m)
    await session.commit()

    response = await client.put(f"/api/v1/db/memberships/{m.id}", json={
        "days": 10,
        "membership_type": "VIP_PREMIUM",
        "is_active": False
    })

    assert response.status_code == 200
    await session.refresh(m)
    assert m.membership_type == "VIP_PREMIUM"
    assert m.is_active is False
    assert m.end_time is not None
    assert (m.end_time - m.start_time).days == 10


@pytest.mark.asyncio
async def test_delete_membership(client: AsyncClient, session: AsyncSession):
    p = Player(steam_id="123")
    m = Membership(steam_id="123", membership_type="VIP_EXPRESS", is_active=True, start_time=datetime.now(UTC))
    session.add(p)
    session.add(m)
    await session.commit()

    m_id = m.id
    response = await client.delete(f"/api/v1/db/memberships/{m_id}")

    assert response.status_code == 200

    deleted_m = (await session.exec(select(Membership).where(Membership.id == m_id))).first()
    assert deleted_m is None


@pytest.mark.asyncio
async def test_remove_special_role(client: AsyncClient, session: AsyncSession):
    p = Player(steam_id="123")
    r = Role(code="VIP_EXPRESS", name="VIP Express", role_type="VIP", discord_role_id="VIP_EXPRESS")
    session.add(p)
    session.add(r)
    await session.commit()
    assert r.id is not None
    pr = PlayerRole(steam_id="123", role_id=r.id)
    session.add(pr)
    await session.commit()

    response = await client.delete("/api/v1/db/players/123/roles/VIP_EXPRESS")
    assert response.status_code == 200

    deleted_pr = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "123", PlayerRole.role_id == r.id))).first()
    assert deleted_pr is None


@pytest.mark.asyncio
async def test_edit_player(client: AsyncClient, session: AsyncSession):
    p = Player(steam_id="123", discord_id="456", custom_welcome_message="Hola")
    session.add(p)
    await session.commit()

    response = await client.put("/api/v1/db/players/123", json={
        "discord_id": "789",
        "custom_welcome_message": "Adios"
    })
    assert response.status_code == 200

    await session.refresh(p)
    assert p.discord_id == "789"
    assert p.custom_welcome_message == "Adios"


@pytest.mark.asyncio
async def test_edit_membership_dynamic_date_adjustment(client: AsyncClient, session: AsyncSession):
    now = datetime.now(UTC)
    p = Player(steam_id="dynamic_user_1")
    # Register membership types so edit_membership resolves days from DB
    mt_express = MembershipType(code="VIP_EXPRESS", name="VIP Express", default_days=15, is_active=True)
    mt_perm = MembershipType(code="VIP_PERMANENTE", name="VIP Permanente", default_days=0, is_active=True)
    m = Membership(
        steam_id="dynamic_user_1",
        membership_type="VIP_COMUN",
        is_active=True,
        start_time=now,
        end_time=now + timedelta(days=30)
    )
    session.add(p)
    session.add(mt_express)
    session.add(mt_perm)
    session.add(m)
    await session.commit()

    # 1. Edit type to VIP_EXPRESS without passing days -> adjusts to 15 days (from MembershipType.default_days)
    resp1 = await client.put(f"/api/v1/db/memberships/{m.id}", json={
        "membership_type": "VIP_EXPRESS"
    })
    assert resp1.status_code == 200
    await session.refresh(m)
    assert m.membership_type == "VIP_EXPRESS"
    assert m.end_time is not None
    assert (m.end_time - m.start_time).days == 15

    # 2. Edit type to VIP_PERMANENTE without passing days -> end_time becomes None (default_days=0)
    resp2 = await client.put(f"/api/v1/db/memberships/{m.id}", json={
        "membership_type": "VIP_PERMANENTE"
    })
    assert resp2.status_code == 200
    await session.refresh(m)
    assert m.membership_type == "VIP_PERMANENTE"
    assert m.end_time is None
    assert m.is_active is True


@pytest.mark.asyncio
async def test_get_paginated_memberships_filtered_by_discord_id(client: AsyncClient, session: AsyncSession):
    now = datetime.now(UTC)
    p1 = Player(steam_id="steam_d1", discord_id="discord_999")
    p2 = Player(steam_id="steam_d2", discord_id="discord_888")
    m1 = Membership(steam_id="steam_d1", membership_type="VIP_COMUN", is_active=True, start_time=now)
    m2 = Membership(steam_id="steam_d1", membership_type="VIP_EXPRESS", is_active=False, start_time=now - timedelta(days=20))
    m3 = Membership(steam_id="steam_d2", membership_type="VIP_COMUN", is_active=True, start_time=now)
    session.add_all([p1, p2, m1, m2, m3])
    await session.commit()

    # Query for discord_999
    res = await client.get("/api/v1/db/memberships?discord_id=discord_999")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["memberships"]) == 2
    for item in data["memberships"]:
        assert item["steam_id"] == "steam_d1"
        assert "rcon_sync_status" in item


@pytest.mark.asyncio
async def test_link_account_prevent_duplicate_linking(client: AsyncClient, session: AsyncSession):
    # 1. Link discord_1 to steam_1 -> 200
    resp1 = await client.post("/api/v1/db/players/link", json={
        "discord_id": "discord_1",
        "steam_id": "steam_1"
    })
    assert resp1.status_code == 200

    # 2. Idempotent link (same discord and same steam) -> 200
    resp_idem = await client.post("/api/v1/db/players/link", json={
        "discord_id": "discord_1",
        "steam_id": "steam_1"
    })
    assert resp_idem.status_code == 200

    # 3. Another discord user tries to link to steam_1 -> 400
    resp_dup_discord = await client.post("/api/v1/db/players/link", json={
        "discord_id": "discord_2",
        "steam_id": "steam_1"
    })
    assert resp_dup_discord.status_code == 400
    assert "ya está vinculado a otra cuenta de Discord" in resp_dup_discord.json()["detail"]

    # 4. discord_1 tries to link to steam_2 -> 400
    resp_dup_steam = await client.post("/api/v1/db/players/link", json={
        "discord_id": "discord_1",
        "steam_id": "steam_2"
    })
    assert resp_dup_steam.status_code == 400
    assert "ya está vinculada al Steam ID 'steam_1'" in resp_dup_steam.json()["detail"]


@pytest.mark.asyncio
async def test_edit_player_prevent_duplicate_discord(client: AsyncClient, session: AsyncSession):
    p1 = Player(steam_id="steam_a", discord_id="disc_a")
    p2 = Player(steam_id="steam_b", discord_id="disc_b")
    session.add_all([p1, p2])
    await session.commit()

    # Try to edit steam_a to use disc_b
    resp = await client.put("/api/v1/db/players/steam_a", json={
        "discord_id": "disc_b"
    })
    assert resp.status_code == 400
    assert "ya está vinculada al Steam ID 'steam_b'" in resp.json()["detail"]
