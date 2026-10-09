from datetime import UTC, datetime, timedelta

import pytest
import src.connections.apis.rcon as rcon_module
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
from src.modules.v1.services.players_service import PlayersService
from wardogs_schemas import v1 as schemas


@pytest.fixture(autouse=True)
def mock_rcon(mocker):
    mocker.patch.object(rcon_module.rcon_client, 'get_reserved_slots', return_value=schemas.ReservedSlots(reservedSlots=[]))
    mocker.patch.object(rcon_module.rcon_client, 'sync_reserved_slots', return_value=None)


@pytest.mark.asyncio
async def test_vip_expiry_revokes_vip_role_but_preserves_special_role(session: AsyncSession, client: AsyncClient):
    now = datetime.now(UTC)
    
    # 1. Create Roles: VIP Común (VIP) and Fundador (SPECIAL)
    vip_role = Role(code="VIP_COMUN", name="VIP COMUN", role_type="VIP", discord_role_id="111111111")
    fundador_role = Role(code="VIP_FUNDADOR", name="FUNDADOR", role_type="SPECIAL", discord_role_id="222222222")
    session.add(vip_role)
    session.add(fundador_role)
    await session.commit()
    await session.refresh(vip_role)
    await session.refresh(fundador_role)

    # 2. Create MembershipType linked to vip_role
    m_type = MembershipType(
        code="VIP_COMUN",
        name="VIP Común",
        price_usd=6,
        default_days=30,
        role_id=vip_role.id,
        is_active=True
    )
    session.add(m_type)

    # 3. Create Player with both VIP and Fundador in PlayerRole
    player = Player(steam_id="STEAM_FOUNDER_VIP", discord_id="999999999")
    session.add(player)
    await session.commit()

    assert vip_role.id is not None and fundador_role.id is not None
    pr_vip = PlayerRole(steam_id="STEAM_FOUNDER_VIP", role_id=vip_role.id)
    pr_fundador = PlayerRole(steam_id="STEAM_FOUNDER_VIP", role_id=fundador_role.id)
    session.add(pr_vip)
    session.add(pr_fundador)

    # 4. Add an expired VIP membership
    m = Membership(
        steam_id="STEAM_FOUNDER_VIP",
        membership_type="VIP_COMUN",
        is_active=True,
        start_time=now - timedelta(days=35),
        end_time=now - timedelta(days=5)
    )
    session.add(m)
    await session.commit()

    # 5. Run sync
    resp = await client.post("/api/v1/db/sync_memberships")
    assert resp.status_code == 200

    # 6. Verify PlayerRole: VIP was deleted, but Fundador remains!
    remaining_prs = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "STEAM_FOUNDER_VIP"))).all()
    remaining_role_ids = [pr.role_id for pr in remaining_prs]
    
    assert vip_role.id not in remaining_role_ids, "VIP role should be revoked upon expiration"
    assert fundador_role.id in remaining_role_ids, "Fundador (SPECIAL) role must NOT be revoked upon VIP expiration"

    # 7. Verify sync_data in response: active_memberships is empty, special_roles has Fundador
    sync_data = resp.json()["sync_data"]
    user_entry = next(u for u in sync_data if u["discord_id"] == "999999999")
    assert user_entry["active_memberships"] == []
    assert user_entry["special_roles"] == [222222222]


@pytest.mark.asyncio
async def test_multiple_active_vip_memberships_same_role(session: AsyncSession, client: AsyncClient):
    now = datetime.now(UTC)
    
    vip_role = Role(code="VIP_COMUN", name="VIP COMUN", role_type="VIP", discord_role_id="111111111")
    session.add(vip_role)
    await session.commit()
    await session.refresh(vip_role)

    m_type = MembershipType(
        code="VIP_COMUN",
        name="VIP Común",
        price_usd=6,
        role_id=vip_role.id,
        is_active=True
    )
    session.add(m_type)

    player = Player(steam_id="STEAM_MULTI_VIP", discord_id="888888888")
    session.add(player)
    assert vip_role.id is not None
    session.add(PlayerRole(steam_id="STEAM_MULTI_VIP", role_id=vip_role.id))

    # One expired membership, one active membership
    m1 = Membership(
        steam_id="STEAM_MULTI_VIP",
        membership_type="VIP_COMUN",
        is_active=True,
        start_time=now - timedelta(days=35),
        end_time=now - timedelta(days=5)
    )
    m2 = Membership(
        steam_id="STEAM_MULTI_VIP",
        membership_type="VIP_COMUN",
        is_active=True,
        start_time=now - timedelta(days=5),
        end_time=now + timedelta(days=25)
    )
    session.add(m1)
    session.add(m2)
    await session.commit()

    resp = await client.post("/api/v1/db/sync_memberships")
    assert resp.status_code == 200

    # m1 should be inactive, m2 active
    await session.refresh(m1)
    await session.refresh(m2)
    assert m1.is_active is False
    assert m2.is_active is True

    # PlayerRole should still have VIP role because m2 is active!
    prs = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "STEAM_MULTI_VIP"))).all()
    assert any(pr.role_id == vip_role.id for pr in prs)


@pytest.mark.asyncio
async def test_player_profile_isolates_special_roles(session: AsyncSession):
    vip_role = Role(code="VIP_COMUN", name="VIP COMUN", role_type="VIP")
    fundador_role = Role(code="VIP_FUNDADOR", name="FUNDADOR", role_type="SPECIAL")
    session.add(vip_role)
    session.add(fundador_role)
    await session.commit()
    await session.refresh(vip_role)
    await session.refresh(fundador_role)

    player = Player(steam_id="STEAM_PROFILE_TEST", in_game_name="ElPadrino", observations="Buen jugador")
    session.add(player)
    assert vip_role.id is not None and fundador_role.id is not None
    session.add(PlayerRole(steam_id="STEAM_PROFILE_TEST", role_id=vip_role.id))
    session.add(PlayerRole(steam_id="STEAM_PROFILE_TEST", role_id=fundador_role.id))
    await session.commit()

    profile = await PlayersService.get_by_steam("STEAM_PROFILE_TEST", session)
    
    # special_roles should ONLY contain "FUNDADOR", not "VIP COMUN"
    assert profile["special_roles"] == ["FUNDADOR"]
    assert profile["active_role"] == "VIP"
    assert profile["observations"] == "Buen jugador"


@pytest.mark.asyncio
async def test_membership_with_attached_special_role(session: AsyncSession, client: AsyncClient):
    now = datetime.now(UTC)

    # 1. Create Roles: VIP Común (VIP) and Fundador (SPECIAL)
    vip_role = Role(code="VIP_ATTACH_COMUN", name="VIP ATTACH COMUN", role_type="VIP", discord_role_id="555111")
    fundador_role = Role(code="VIP_ATTACH_FUNDADOR", name="VIP ATTACH FUNDADOR", role_type="SPECIAL", discord_role_id="555222")
    session.add(vip_role)
    session.add(fundador_role)
    await session.commit()
    await session.refresh(vip_role)
    await session.refresh(fundador_role)

    # 2. Create MembershipType linked to vip_role
    m_type = MembershipType(
        code="VIP_ATTACH_COMUN",
        name="VIP Attach Común",
        price_usd=6,
        default_days=30,
        role_id=vip_role.id,
        is_active=True
    )
    session.add(m_type)

    player = Player(steam_id="STEAM_ATTACH_TEST", discord_id="555333")
    session.add(player)
    await session.commit()

    # 3. Add membership via API with attached special role
    add_payload = {
        "steam_id": "STEAM_ATTACH_TEST",
        "membership_type": "VIP_ATTACH_COMUN",
        "days": 30,
        "special_role": "VIP_ATTACH_FUNDADOR"
    }
    resp = await client.post("/api/v1/db/players/membership", json=add_payload)
    assert resp.status_code == 200

    # 4. Verify membership record has BOTH role_granted_id AND special_role_id
    m_row = (await session.exec(
        select(Membership).where(Membership.steam_id == "STEAM_ATTACH_TEST", Membership.is_active == True)
    )).first()
    assert m_row is not None
    assert m_row.role_granted_id == vip_role.id, "Membership must record the granted VIP role"
    assert m_row.special_role_id == fundador_role.id, "Membership must record the attached special role"

    # 5. Verify PlayerRole has BOTH roles assigned
    prs = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "STEAM_ATTACH_TEST"))).all()
    assigned_role_ids = {pr.role_id for pr in prs}
    assert vip_role.id in assigned_role_ids
    assert fundador_role.id in assigned_role_ids

    # 6. Verify paginated memberships returns both roles
    resp_list = await client.get("/api/v1/db/memberships?page=1&limit=10")
    assert resp_list.status_code == 200
    m_entry = next(m for m in resp_list.json()["memberships"] if m["steam_id"] == "STEAM_ATTACH_TEST")
    assert m_entry["role_granted_id"] == vip_role.id
    assert m_entry["role_granted_name"] == vip_role.name
    assert m_entry["special_role_id"] == fundador_role.id
    assert m_entry["special_role"] == fundador_role.name

    # 7. Test renewal inherits attached special role if omitted
    renew_payload = {
        "steam_id": "STEAM_ATTACH_TEST",
        "membership_type": "VIP_ATTACH_COMUN",
        "days": 30
        # special_role omitted!
    }
    resp_renew = await client.post("/api/v1/db/players/membership", json=renew_payload)
    assert resp_renew.status_code == 200

    renewed_m = (await session.exec(
        select(Membership).where(Membership.steam_id == "STEAM_ATTACH_TEST", Membership.is_active == True)
    )).first()
    assert renewed_m is not None
    assert renewed_m.role_granted_id == vip_role.id
    assert renewed_m.special_role_id == fundador_role.id, "Renewal must inherit the attached special role"


@pytest.mark.asyncio
async def test_membership_deletion_cleans_player_roles(session: AsyncSession, client: AsyncClient):
    """Deleting an active membership must remove its VIP role from player_roles so no orphans remain."""
    role = Role(code="VIP_DEL_TEST", name="VIP Del Test", role_type="VIP", discord_role_id="111999888")
    session.add(role)
    await session.commit()
    await session.refresh(role)

    mt = MembershipType(code="VIP_DEL_TEST", name="VIP Del Test", role_id=role.id, default_days=30, price_usd=6)
    session.add(mt)

    player = Player(steam_id="STEAM_DEL_TEST", discord_id="777666555")
    session.add(player)
    await session.commit()

    # Add membership
    add_resp = await client.post("/api/v1/db/players/membership", json={
        "steam_id": "STEAM_DEL_TEST",
        "membership_type": "VIP_DEL_TEST",
        "days": 30
    })
    assert add_resp.status_code == 200

    m_row = (await session.exec(select(Membership).where(Membership.steam_id == "STEAM_DEL_TEST", Membership.is_active == True))).first()
    assert m_row is not None
    mem_id = m_row.id

    # Verify role exists in player_roles
    pr_before = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "STEAM_DEL_TEST", PlayerRole.role_id == role.id))).first()
    assert pr_before is not None

    # Delete membership
    del_resp = await client.delete(f"/api/v1/db/memberships/{mem_id}")
    assert del_resp.status_code == 200

    # Verify role was cleaned from player_roles
    pr_after = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "STEAM_DEL_TEST", PlayerRole.role_id == role.id))).first()
    assert pr_after is None, "PlayerRole must be deleted when the active membership is deleted"


@pytest.mark.asyncio
async def test_membership_edit_type_updates_granted_role(session: AsyncSession, client: AsyncClient):
    """Editing membership_type must update role_granted_id and player_roles to the new type's role."""
    r1 = Role(code="VIP_TYPE_A", name="VIP Type A", role_type="VIP", discord_role_id="111111111")
    r2 = Role(code="VIP_TYPE_B", name="VIP Type B", role_type="VIP", discord_role_id="222222222")
    session.add(r1)
    session.add(r2)
    await session.commit()
    await session.refresh(r1)
    await session.refresh(r2)

    mt1 = MembershipType(code="VIP_TYPE_A", name="VIP Type A", role_id=r1.id, default_days=30, price_usd=6)
    mt2 = MembershipType(code="VIP_TYPE_B", name="VIP Type B", role_id=r2.id, default_days=30, price_usd=12)
    session.add(mt1)
    session.add(mt2)

    player = Player(steam_id="STEAM_EDIT_TYPE", discord_id="333444555")
    session.add(player)
    await session.commit()

    add_resp = await client.post("/api/v1/db/players/membership", json={
        "steam_id": "STEAM_EDIT_TYPE",
        "membership_type": "VIP_TYPE_A",
        "days": 30
    })
    assert add_resp.status_code == 200

    m_row = (await session.exec(select(Membership).where(Membership.steam_id == "STEAM_EDIT_TYPE", Membership.is_active == True))).first()
    assert m_row is not None and m_row.id is not None
    assert r1.id is not None and r2.id is not None
    assert m_row.role_granted_id == r1.id

    # Edit membership to VIP_TYPE_B
    edit_resp = await client.put(f"/api/v1/db/memberships/{m_row.id}", json={
        "membership_type": "VIP_TYPE_B"
    })
    assert edit_resp.status_code == 200

    await session.refresh(m_row)
    assert m_row.role_granted_id == r2.id, "role_granted_id must be updated to new role"

    # PlayerRole should now have r2 and NOT r1
    prs = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == "STEAM_EDIT_TYPE"))).all()
    pr_ids = {pr.role_id for pr in prs}
    assert r2.id in pr_ids
    assert r1.id not in pr_ids


@pytest.mark.asyncio
async def test_membership_negative_days_rejected(client: AsyncClient, session: AsyncSession):
    p = Player(steam_id="STEAM_NEG_DAYS")
    session.add(p)
    await session.commit()

    resp = await client.post("/api/v1/db/players/membership", json={
        "steam_id": "STEAM_NEG_DAYS",
        "membership_type": "VIP_COMUN",
        "days": -5
    })
    assert resp.status_code == 400
    assert "positivo" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_membership_extend_reactivates_expired_membership(client: AsyncClient, session: AsyncSession):
    vip_role = Role(code="VIP_EXT_REACT", name="VIP Reactivate", role_type="VIP")
    session.add(vip_role)
    p = Player(steam_id="STEAM_EXT_REACT")
    session.add(p)
    await session.commit()
    await session.refresh(vip_role)

    now = datetime.now(UTC)
    expired_m = Membership(
        steam_id="STEAM_EXT_REACT",
        membership_type="VIP_EXT_REACT",
        role_granted_id=vip_role.id,
        is_active=False,
        start_time=now - timedelta(days=40),
        end_time=now - timedelta(days=10)
    )
    session.add(expired_m)
    await session.commit()
    await session.refresh(expired_m)

    # Extend expired membership by 15 days
    resp = await client.put(f"/api/v1/db/memberships/{expired_m.id}", json={
        "add_days": 15
    })
    assert resp.status_code == 200

    await session.refresh(expired_m)
    assert expired_m.is_active is True
    # The end_time should be extended from now (+15 days), not from the expired past date
    m_end = expired_m.end_time
    assert m_end is not None
    if m_end.tzinfo is None:
        m_end = m_end.replace(tzinfo=UTC)
    assert m_end > now + timedelta(days=14)

    # Role in PlayerRole should be restored
    pr = (await session.exec(select(PlayerRole).where(
        PlayerRole.steam_id == "STEAM_EXT_REACT",
        PlayerRole.role_id == vip_role.id
    ))).first()
    assert pr is not None


@pytest.mark.asyncio
async def test_compensate_memberships_validation(client: AsyncClient):
    resp_zero = await client.post("/api/v1/db/memberships/compensate", json={"days": 0})
    assert resp_zero.status_code == 400

    resp_neg = await client.post("/api/v1/db/memberships/compensate", json={"days": -10})
    assert resp_neg.status_code == 400


