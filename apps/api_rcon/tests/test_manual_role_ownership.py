"""Legacy manual role commands cannot change Laracord membership benefits."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from wardogs_config import BOT_SETTINGS

from src.connections.databases.db import Membership, MembershipType, Player, PlayerRole, Role
from test_membership_deliveries import (
    ADD_URL, QUEUE_URL, initial_player, payload, queued, deliveries_mock, renewal_player,
)
from test_membership_renewals import ACTOR, GUILD, NEW_ROLE, BADGE, STEAM, USER


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["vip", "type", "historical_grant", "historical_badge"])
@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_manual_membership_role_change_rejected_before_mutations(client, session, monkeypatch, mocker, owner, method):
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    role = Role(code="PROTECTED", name="Protected", role_type="VIP" if owner == "vip" else "SPECIAL")
    player = Player(steam_id="manual-role-player")
    session.add_all([role, player])
    await session.flush()
    if owner == "type":
        # A membership role remains protected even when its type is inactive.
        session.add(MembershipType(code="inactive", name="Inactive", role_id=role.id, is_active=False))
    elif owner.startswith("historical"):
        fields = {"role_granted_id" if owner == "historical_grant" else "special_role_id": role.id}
        session.add(Membership(steam_id=player.steam_id, membership_type="historical", is_active=False,
                               end_time=datetime.now(timezone.utc) - timedelta(days=1), **fields))
    if method == "DELETE":
        session.add(PlayerRole(steam_id=player.steam_id, role_id=role.id))
    await session.commit()
    add = mocker.spy(session, "add")
    delete = mocker.spy(session, "delete")
    commit = mocker.spy(session, "commit")

    response = await client.request(method, f"/api/v1/db/players/{player.steam_id}/roles/{role.code}")

    assert response.status_code == 409
    assert "Laracord" in response.json()["detail"]
    add.assert_not_called()
    delete.assert_not_called()
    commit.assert_not_called()
    assigned = await session.get(PlayerRole, (player.steam_id, role.id))
    assert (assigned is not None) == (method == "DELETE")


@pytest.mark.asyncio
@pytest.mark.parametrize("role_type,code", [("SYSTEM", "LINK"), ("SPECIAL", "HELPER")])
async def test_manual_non_membership_roles_remain_available(client, session, monkeypatch, role_type, code):
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    role = Role(code=code, name=code, role_type=role_type)
    player = Player(steam_id="ordinary-role-player")
    session.add_all([role, player])
    await session.commit()
    url = f"/api/v1/db/players/{player.steam_id}/roles/{code}"
    assert (await client.post(url)).status_code == 200
    assert await session.get(PlayerRole, (player.steam_id, role.id)) is not None
    assert (await client.delete(url)).status_code == 200
    assert await session.get(PlayerRole, (player.steam_id, role.id)) is None


@pytest.mark.asyncio
async def test_enabled_legacy_management_preserves_manual_vip_behavior(client, session, monkeypatch):
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", True)
    role = Role(code="LEGACY_VIP", name="Legacy VIP", role_type="VIP")
    player = Player(steam_id="legacy-role-player")
    session.add_all([role, player])
    await session.commit()
    url = f"/api/v1/db/players/{player.steam_id}/roles/{role.code}"
    assert (await client.post(url)).status_code == 200
    assert await session.get(PlayerRole, (player.steam_id, role.id)) is not None
    assert (await client.delete(url)).status_code == 200
    assert await session.get(PlayerRole, (player.steam_id, role.id)) is None


@pytest.mark.asyncio
async def test_manual_commands_preserve_active_membership_and_pending_role_delivery(client, session, initial_player, deliveries_mock, monkeypatch):
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    created = await client.post(ADD_URL, json=payload(special_role=BADGE))
    assert created.status_code == 200
    original = created.json()
    membership = (await session.exec(select(Membership))).one()
    before = await queued(client)
    assert len(before) == 1
    assert set(before[0]["role_ids_to_add"]) == {NEW_ROLE, BADGE}

    for role in initial_player[2:]:
        url = f"/api/v1/db/players/{STEAM}/roles/{role.code}"
        assert (await client.post(url)).status_code == 409
        assert (await client.delete(url)).status_code == 409
        assert await session.get(PlayerRole, (STEAM, role.id)) is not None

    await session.refresh(membership)
    assert membership.is_active and membership.role_granted_id == initial_player[2].id
    assert membership.special_role_id == initial_player[3].id
    assert membership.id == original["membership"]["id"]
    assert await queued(client) == before
    deliveries_mock[0].assert_awaited_once()


@pytest.mark.asyncio
async def test_membership_lifecycle_remains_available_when_manual_management_disabled(client, session, initial_player, deliveries_mock, monkeypatch):
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    created = await client.post(ADD_URL, json=payload(special_role=BADGE))
    assert created.status_code == 200
    ack = await client.post(f"{QUEUE_URL}/{created.json()['delivery']['id']}/complete",
                            json={"guild_id": GUILD, "user_id": USER})
    assert ack.status_code == 200
    renewal = await client.post("/api/v1/db/players/membership/renew", json={
        "steam_id": STEAM, "membership_type": "regular", "guild_id": GUILD,
        "actor_id": ACTOR, "operation_id": "renew-after-guard",
    })
    assert renewal.status_code == 200 and renewal.json()["status"] == "SCHEDULED"
    assert await session.get(PlayerRole, (STEAM, initial_player[2].id)) is not None

    removed = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={
        "guild_id": GUILD, "actor_id": ACTOR, "operation_id": "remove-after-guard",
    })
    assert removed.status_code == 200
    assert await session.get(PlayerRole, (STEAM, initial_player[2].id)) is None
    assert await session.get(PlayerRole, (STEAM, initial_player[3].id)) is not None
