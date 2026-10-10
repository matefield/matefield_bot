"""Direct cancellation preserves history and resumes only the pending Discord delivery."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlmodel import select

from src.connections.apis.rcon import RCONManager
from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import (
    Membership, MembershipRemovalOperation, MembershipType, Player, PlayerRole,
    RconServer, Role, RoleDiscordBinding,
)
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import MembershipWarconDelivery

STEAM_ID = "76561198000000051"
USER_ID = "111111111111111111"
GUILD_ID = "222222222222222222"
OTHER_GUILD_ID = "222222222222222223"
ACTOR_ID = "333333333333333333"
VIP_ROLE_ID = "444444444444444444"
SPECIAL_ROLE_ID = "444444444444444445"
SYSTEM_ROLE_ID = "444444444444444446"


def payload(**overrides):
    return {"operation_id": "remove-1", "guild_id": GUILD_ID, "actor_id": ACTOR_ID, **overrides}


def remove_url(steam_id=STEAM_ID):
    return f"/api/v1/db/players/{steam_id}/membership/remove"


async def complete(client, operation_id="remove-1", **overrides):
    return await client.post(f"{remove_url()}/{operation_id}/complete", json={
        "guild_id": GUILD_ID, "actor_id": ACTOR_ID, **overrides,
    })


@pytest.fixture
def removal_delivery(monkeypatch):
    for key, value in {
        "WARCON_URL": "http://warcon.test", "WARCON_ORG_ID": "test-org",
        "WARCON_SERVER_ID": "test-server", "WARCON_API_TOKEN": "test-only",
    }.items():
        monkeypatch.setattr(ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS, key, value)
    monkeypatch.setattr(ENVIRONMENT_SETTINGS.SECURITY_SETTINGS, "DISCORD_GUILD_IDS", f"{GUILD_ID},{OTHER_GUILD_ID}")
    mock = AsyncMock(return_value=MembershipWarconDelivery(
        status="SUCCESS", server_id="test-server", entry_id="test-entry",
    ))
    monkeypatch.setattr(WarconClient, "remove_reserved_slot", mock)
    return mock


@pytest_asyncio.fixture
async def membership_player(session):
    player = Player(steam_id=STEAM_ID, discord_id=USER_ID)
    vip = Role(code="VIP", name="VIP Normal", role_type="VIP")
    special = Role(code="FOUNDER", name="Fundador", role_type="SPECIAL")
    system = Role(code="STAFF", name="Staff", role_type="SYSTEM")
    session.add_all([player, vip, special, system])
    await session.flush()
    session.add(MembershipType(code="regular", name="VIP Normal", default_days=30, role_id=vip.id))
    for role, discord_role in [(vip, VIP_ROLE_ID), (special, SPECIAL_ROLE_ID), (system, SYSTEM_ROLE_ID)]:
        session.add(RoleDiscordBinding(role_id=role.id, guild_id=GUILD_ID,
                                       discord_role_id=discord_role, configured_by=ACTOR_ID))
        session.add(PlayerRole(steam_id=STEAM_ID, role_id=role.id))
    membership = Membership(steam_id=STEAM_ID, membership_type="regular", role_granted_id=vip.id,
                            special_role_id=special.id, end_time=datetime.now(timezone.utc) + timedelta(days=30))
    session.add(membership)
    await session.commit()
    return player, membership, vip, special, system


@pytest.mark.asyncio
async def test_removal_confirms_warcon_before_deactivation_and_preserves_history(
    client, session, membership_player, removal_delivery, monkeypatch,
):
    player, membership, vip, special, system = membership_player
    original_end = membership.end_time
    global_sync = AsyncMock()
    monkeypatch.setattr(RCONManager, "get_default_server", global_sync)

    async def observe_before_commit(**arguments):
        row = (await session.exec(select(Membership))).one()
        assert row.is_active is True
        assert await session.get(PlayerRole, (STEAM_ID, vip.id)) is not None
        assert arguments == {"steam_id": STEAM_ID, "membership_ids": [membership.id]}
        return MembershipWarconDelivery(status="SUCCESS", server_id="test-server", entry_id="test-entry")

    removal_delivery.side_effect = observe_before_commit
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 200
    result = response.json()
    assert result["steam_id"] == STEAM_ID
    assert result["removed_membership_ids"] == [membership.id]
    assert result["discord"] == {"user_id": USER_ID, "guild_id": GUILD_ID, "role_ids": [VIP_ROLE_ID]}
    assert result["warcon"]["status"] == "SUCCESS"
    await session.refresh(membership)
    assert membership.is_active is False
    assert membership.end_time == original_end.replace(tzinfo=None)
    assert membership.rcon_sync_status == "SUCCESS"
    assert await session.get(PlayerRole, (STEAM_ID, vip.id)) is None
    assert await session.get(PlayerRole, (STEAM_ID, special.id)) is not None
    assert await session.get(PlayerRole, (STEAM_ID, system.id)) is not None
    receipt = (await session.exec(select(MembershipRemovalOperation))).one()
    assert receipt.discord_roles_removed is False
    global_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_global_legacy_memberships_are_cancelled_and_note_ownership_includes_history(
    client, session, membership_player, removal_delivery,
):
    _, membership, vip, _, _ = membership_player
    second = Membership(steam_id=STEAM_ID, membership_type="regular", role_granted_id=vip.id)
    historical = Membership(steam_id=STEAM_ID, membership_type="regular", role_granted_id=vip.id, is_active=False)
    session.add_all([second, historical])
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 200
    assert response.json()["removed_membership_ids"] == [membership.id, second.id]
    removal_delivery.assert_awaited_once_with(steam_id=STEAM_ID, membership_ids=[membership.id, second.id, historical.id])
    rows = (await session.exec(select(Membership))).all()
    assert len(rows) == 3 and all(not row.is_active for row in rows)
    assert await session.get(PlayerRole, (STEAM_ID, vip.id)) is None


@pytest.mark.asyncio
async def test_server_membership_keeps_its_shared_role(client, session, membership_player, removal_delivery):
    _, global_membership, vip, _, _ = membership_player
    server = RconServer(name="Other", ip="127.0.0.1", port=7776, password="test-only")
    session.add(server)
    await session.flush()
    specific = Membership(steam_id=STEAM_ID, membership_type="regular", role_granted_id=vip.id, server_id=server.id)
    session.add(specific)
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 200
    assert response.json()["removed_membership_ids"] == [global_membership.id]
    assert response.json()["discord"]["role_ids"] == []
    await session.refresh(specific)
    assert specific.is_active is True
    assert await session.get(PlayerRole, (STEAM_ID, vip.id)) is not None
    assert (await session.exec(select(MembershipRemovalOperation))).one().discord_roles_removed is True
    removal_delivery.assert_awaited_once_with(steam_id=STEAM_ID, membership_ids=[global_membership.id])


@pytest.mark.asyncio
@pytest.mark.parametrize("role_type", ["SPECIAL", "SYSTEM"])
async def test_logical_staff_and_special_roles_are_never_retired(
    client, session, membership_player, removal_delivery, role_type,
):
    _, membership, vip, _, _ = membership_player
    vip.role_type = role_type
    session.add(vip)
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 200
    assert response.json()["discord"]["role_ids"] == []
    assert await session.get(PlayerRole, (STEAM_ID, vip.id)) is not None


@pytest.mark.asyncio
async def test_vip_binding_shared_with_staff_is_protected(client, session, membership_player, removal_delivery):
    _, _, vip, _, system = membership_player
    binding = (await session.exec(select(RoleDiscordBinding).where(RoleDiscordBinding.role_id == system.id))).one()
    binding.discord_role_id = VIP_ROLE_ID
    session.add(binding)
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 200
    assert response.json()["discord"]["role_ids"] == []
    assert await session.get(PlayerRole, (STEAM_ID, system.id)) is not None


@pytest.mark.asyncio
async def test_special_badge_remains_even_when_its_role_type_was_vip(
    client, session, membership_player, removal_delivery,
):
    _, _, _, special, _ = membership_player
    special.role_type = "VIP"
    session.add(special)
    await session.commit()
    result = (await client.post(remove_url(), json=payload())).json()
    assert result["discord"]["role_ids"] == [VIP_ROLE_ID]
    assert await session.get(PlayerRole, (STEAM_ID, special.id)) is not None


@pytest.mark.asyncio
async def test_missing_role_configuration_rejects_before_warcon(
    client, session, membership_player, removal_delivery,
):
    _, _, vip, _, _ = membership_player
    binding = (await session.exec(select(RoleDiscordBinding).where(RoleDiscordBinding.role_id == vip.id))).one()
    await session.delete(binding)
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_removal_role_configuration_missing"
    removal_delivery.assert_not_awaited()
    assert (await session.exec(select(Membership))).one().is_active is True
    assert (await session.exec(select(MembershipRemovalOperation))).all() == []


@pytest.mark.asyncio
async def test_warcon_failure_keeps_membership_roles_and_allows_same_operation_retry(
    client, session, membership_player, removal_delivery,
):
    _, membership, vip, _, _ = membership_player
    vip_id = vip.id
    removal_delivery.side_effect = [
        MembershipWarconDelivery(status="FAILED", server_id="test-server", error="Manual entry is protected"),
        MembershipWarconDelivery(status="SUCCESS", server_id="test-server"),
    ]
    failed = await client.post(remove_url(), json=payload())
    assert failed.status_code == 502
    assert failed.json()["detail"]["code"] == "membership_removal_warcon_failed"
    current = (await session.exec(select(Membership))).one()
    assert current.is_active is True
    assert await session.get(PlayerRole, (STEAM_ID, vip_id)) is not None
    assert (await session.exec(select(MembershipRemovalOperation))).all() == []
    retried = await client.post(remove_url(), json=payload())
    assert retried.status_code == 200
    assert retried.json()["replayed"] is False
    assert removal_delivery.await_count == 2


@pytest.mark.asyncio
async def test_replay_is_safe_and_actor_is_audited_not_part_of_operation_identity(
    client, session, membership_player, removal_delivery,
):
    first = (await client.post(remove_url(), json=payload())).json()
    retry = await client.post(remove_url(), json=payload(actor_id="333333333333333334"))
    assert retry.status_code == 200
    assert retry.json() == {**first, "replayed": True}
    assert (await session.exec(select(MembershipRemovalOperation))).one().actor_id == ACTOR_ID
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_command_resumes_the_pending_canonical_operation(client, membership_player, removal_delivery):
    first = (await client.post(remove_url(), json=payload())).json()
    retry = await client.post(remove_url(), json=payload(operation_id="new-command"))
    assert retry.status_code == 200
    assert retry.json() == {**first, "replayed": True}
    assert retry.json()["operation_id"] == "remove-1"
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_delivery_in_other_guild_cannot_be_taken_over(client, membership_player, removal_delivery):
    await client.post(remove_url(), json=payload())
    response = await client.post(remove_url(), json=payload(operation_id="new-command", guild_id=OTHER_GUILD_ID))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_removal_pending_other_guild"
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_operation_id_cannot_be_reused_for_another_player(client, session, membership_player, removal_delivery):
    await client.post(remove_url(), json=payload())
    another = Player(steam_id="76561198000000052", discord_id="111111111111111112")
    session.add(another)
    await session.commit()
    response = await client.post(remove_url(another.steam_id), json=payload())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_removal_operation_conflict"
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("discord_id", [None, "111111111111111112"])
async def test_receipt_replay_rejects_unlinked_or_relinked_user(
    client, session, membership_player, removal_delivery, discord_id,
):
    await client.post(remove_url(), json=payload())
    player = membership_player[0]
    player.discord_id = discord_id
    session.add(player)
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_removal_discord_account_missing"
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_is_idempotent_and_other_admin_can_complete(client, session, membership_player, removal_delivery):
    await client.post(remove_url(), json=payload())
    for _ in range(2):
        response = await complete(client, actor_id="333333333333333334")
        assert response.status_code == 200
        assert response.json() == {"ok": True, "operation_id": "remove-1"}
    assert (await session.exec(select(MembershipRemovalOperation))).one().discord_roles_removed is True
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_requires_receipt_player_and_guild(client, membership_player, removal_delivery):
    await client.post(remove_url(), json=payload())
    unknown = await complete(client, operation_id="unknown")
    assert unknown.status_code == 404
    wrong_guild = await complete(client, guild_id=OTHER_GUILD_ID)
    assert wrong_guild.status_code == 409
    assert wrong_guild.json()["detail"]["code"] == "membership_removal_operation_conflict"


@pytest.mark.asyncio
async def test_new_membership_waits_for_discord_removal_confirmation(
    client, session, membership_player, removal_delivery,
):
    await client.post(remove_url(), json=payload())
    request = {"steam_id": STEAM_ID, "membership_type": "regular"}
    blocked = await client.post("/api/v1/db/players/membership", json=request)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "membership_removal_pending"
    assert len((await session.exec(select(Membership))).all()) == 1
    assert (await complete(client)).status_code == 200
    created = await client.post("/api/v1/db/players/membership", json=request)
    assert created.status_code == 200
    assert len((await session.exec(select(Membership))).all()) == 2


@pytest.mark.asyncio
async def test_stale_receipt_cannot_remove_a_new_membership(client, session, membership_player, removal_delivery):
    await client.post(remove_url(), json=payload())
    await complete(client)
    response = await client.post("/api/v1/db/players/membership", json={"steam_id": STEAM_ID, "membership_type": "regular"})
    assert response.status_code == 200
    replay = await client.post(remove_url(), json=payload())
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "membership_removal_superseded"
    assert any(membership.is_active for membership in (await session.exec(select(Membership))).all())
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_global_membership_does_not_touch_warcon(client, session, membership_player, removal_delivery):
    membership = membership_player[1]
    membership.is_active = False
    session.add(membership)
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "membership_removal_not_found"
    removal_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_guild_and_bad_request_are_rejected_before_writes(client, membership_player, removal_delivery):
    response = await client.post(remove_url(), json=payload(guild_id="999999999999999999"))
    assert response.status_code == 403
    response = await client.post(remove_url(), json=payload(operation_id="../invalid"))
    assert response.status_code == 422
    removal_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_receipt_never_authorizes_another_discord_role_removal(
    client, membership_player, removal_delivery,
):
    first = await client.post(remove_url(), json=payload())
    assert first.status_code == 200
    assert first.json()["discord"]["role_ids"] == [VIP_ROLE_ID]
    assert (await complete(client)).status_code == 200
    replay = await client.post(remove_url(), json=payload())
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["discord"]["role_ids"] == []
    removal_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_specific_server_creation_is_also_blocked_while_discord_roles_are_pending(
    client, session, membership_player, removal_delivery,
):
    await client.post(remove_url(), json=payload())
    server = RconServer(name="Other", ip="127.0.0.1", port=7776, password="test-only")
    session.add(server)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": STEAM_ID, "membership_type": "regular", "server_id": server.id,
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_removal_pending"
    assert len((await session.exec(select(Membership))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"is_active": True}, {"add_days": 1}])
async def test_edit_cannot_reactivate_or_extend_a_membership_while_role_removal_is_pending(
    client, session, membership_player, removal_delivery, changes,
):
    membership_id = membership_player[1].id
    original_end = membership_player[1].end_time
    await client.post(remove_url(), json=payload())
    response = await client.put(f"/api/v1/db/memberships/{membership_id}", json=changes)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_removal_pending"
    row = await session.get(Membership, membership_id)
    assert row.is_active is False
    assert row.end_time.replace(tzinfo=timezone.utc) == original_end


@pytest.mark.asyncio
async def test_legacy_special_badge_shared_with_another_cancelled_vip_retains_player_role(
    client, session, membership_player, removal_delivery,
):
    _, _, _, special, _ = membership_player
    special.role_type = "VIP"
    session.add_all([
        special,
        MembershipType(code="express", name="VIP Express", role_id=special.id),
        Membership(steam_id=STEAM_ID, membership_type="express", role_granted_id=special.id),
    ])
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 200
    assert response.json()["discord"]["role_ids"] == [VIP_ROLE_ID]
    assert len(response.json()["removed_membership_ids"]) == 2
    assert await session.get(PlayerRole, (STEAM_ID, special.id)) is not None
    assert all(not row.is_active for row in (await session.exec(select(Membership))).all())


@pytest.mark.asyncio
async def test_preserving_badges_never_creates_a_role_the_player_did_not_have(
    client, session, membership_player, removal_delivery,
):
    special = membership_player[3]
    existing = await session.get(PlayerRole, (STEAM_ID, special.id))
    await session.delete(existing)
    await session.commit()
    assert (await client.post(remove_url(), json=payload())).status_code == 200
    assert await session.get(PlayerRole, (STEAM_ID, special.id)) is None


@pytest.mark.asyncio
async def test_legacy_membership_without_explicit_role_uses_its_type_binding(
    client, session, membership_player, removal_delivery,
):
    membership = membership_player[1]
    membership.role_granted_id = None
    session.add(membership)
    await session.commit()
    response = await client.post(remove_url(), json=payload())
    assert response.status_code == 200
    assert response.json()["discord"]["role_ids"] == [VIP_ROLE_ID]
    assert await session.get(PlayerRole, (STEAM_ID, membership_player[2].id)) is None
