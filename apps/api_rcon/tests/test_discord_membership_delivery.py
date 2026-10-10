"""Membership commands deliver one player's benefits inline, without a global sync."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.apis.rcon import RCONManager
from src.connections.databases.db import Membership, MembershipType, Player, PlayerRole, Role
from src.modules.v1.services.memberships_service import MembershipsService
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import MembershipWarconDelivery


@pytest.fixture
def warcon_settings(monkeypatch):
    settings = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    for key, value in {
        "WARCON_URL": "http://warcon.test", "WARCON_ORG_ID": "test-org",
        "WARCON_SERVER_ID": "test-server", "WARCON_API_TOKEN": "wck_test_only",
    }.items():
        monkeypatch.setattr(settings, key, value)
    return settings


@pytest.fixture
def delivery(warcon_settings, monkeypatch):
    mock = AsyncMock(return_value=MembershipWarconDelivery(
        status="SUCCESS", server_id="test-server", entry_id="test-entry",
    ))
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", mock)
    return mock


@pytest_asyncio.fixture
async def discord_player(session):
    role = Role(code="EXPRESS", name="Express", role_type="VIP", discord_role_id="123456789012345678")
    player = Player(steam_id="76561198000000001", discord_id="234567890123456789")
    session.add_all([role, player])
    await session.flush()
    membership_type = MembershipType(code="EXPRESS", name="Express", default_days=7, role_id=role.id)
    session.add(membership_type)
    await session.commit()
    return player, membership_type, role


def command_payload(**overrides):
    return {
        "steam_id": "76561198000000001", "membership_type": "express",
        "source": "DISCORD", "operation_id": "345678901234567890", **overrides,
    }


@pytest.mark.asyncio
async def test_discord_creation_returns_saved_dates_roles_and_confirmed_warcon(client, session, discord_player, delivery):
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 200
    result = response.json()
    assert result["discord"] == {"user_id": "234567890123456789", "role_ids": ["123456789012345678"]}
    assert result["membership"]["type"] == "EXPRESS"
    assert result["warcon"]["status"] == "SUCCESS"
    assert result["replayed"] is False
    membership = (await session.exec(select(Membership))).one()
    assert membership.rcon_sync_status == "SUCCESS"
    assert (membership.end_time - membership.start_time).days == 7
    delivery.assert_awaited_once_with(membership.steam_id, membership.id, "Express", membership.end_time.replace(tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_permanent_membership_sends_no_expiry(client, discord_player, delivery):
    response = await client.post("/api/v1/db/players/membership", json=command_payload(days=0))
    assert response.status_code == 200
    assert response.json()["membership"]["end_date"] is None
    assert response.json()["membership"]["server_id"] is None
    assert delivery.await_args.args[-1] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("other_days", [None, 30])
async def test_add_rejects_different_existing_active_plan_without_touching_warcon(client, session, discord_player, delivery, other_days):
    player, _, _ = discord_player
    longer_expiry = datetime.now(timezone.utc) + timedelta(days=other_days) if other_days else None
    other = Membership(steam_id=player.steam_id, membership_type="OTHER", end_time=longer_expiry)
    session.add(other)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "membership_already_active"}
    assert (await session.exec(select(Membership))).one().id == other.id
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_does_not_implicitly_renew_an_active_membership(client, session, discord_player, delivery):
    first = (await client.post("/api/v1/db/players/membership", json=command_payload())).json()
    second = await client.post("/api/v1/db/players/membership", json=command_payload(operation_id="another-operation"))
    assert second.status_code == 409
    assert second.json()["detail"] == {"code": "membership_already_active"}
    rows = (await session.exec(select(Membership))).all()
    assert len(rows) == 1 and rows[0].is_active is True
    assert rows[0].end_time.replace(tzinfo=timezone.utc) == datetime.fromisoformat(first["membership"]["end_date"].replace("Z", "+00:00"))
    assert delivery.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_days,added_days", [(0, 3653)])
async def test_warcon_ten_year_limit_is_validated_before_creation(client, session, discord_player, delivery, existing_days, added_days):
    if existing_days:
        session.add(Membership(steam_id=discord_player[0].steam_id, membership_type="EXPRESS",
                               end_time=datetime.now(timezone.utc) + timedelta(days=existing_days)))
        await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload(days=added_days))
    assert response.status_code == 400
    rows = (await session.exec(select(Membership))).all()
    assert len(rows) == bool(existing_days)
    assert all(row.is_active for row in rows)
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_refuses_a_missing_discord_role(client, session, discord_player, delivery):
    await client.post("/api/v1/db/players/membership", json=command_payload())
    role = discord_player[2]
    role.discord_role_id = None
    session.add(role)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 409
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_retry_does_not_create_membership_or_add_days_twice(client, session, discord_player, delivery):
    first = (await client.post("/api/v1/db/players/membership", json=command_payload())).json()
    second = (await client.post("/api/v1/db/players/membership", json=command_payload())).json()
    assert second["replayed"] is True
    assert second["membership"] == first["membership"]
    assert len((await session.exec(select(Membership))).all()) == 1
    assert delivery.await_count == 2


@pytest.mark.asyncio
async def test_retry_with_different_input_is_rejected(client, session, discord_player, delivery):
    await client.post("/api/v1/db/players/membership", json=command_payload())
    response = await client.post("/api/v1/db/players/membership", json=command_payload(days=42))
    assert response.status_code == 409
    assert len((await session.exec(select(Membership))).all()) == 1
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_warcon_failure_reports_partial_creation_and_can_be_retried(client, session, discord_player, delivery):
    delivery.side_effect = [
        MembershipWarconDelivery(status="FAILED", server_id="test-server", error="Warcon no confirmó el slot."),
        MembershipWarconDelivery(status="SUCCESS", server_id="test-server", entry_id="test-entry"),
    ]
    first = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert first.json()["warcon"]["status"] == "FAILED"
    assert first.json()["discord"]["role_ids"] == ["123456789012345678"]
    membership = (await session.exec(select(Membership))).one()
    assert membership.rcon_sync_status == "FAILED"
    listing = (await client.get("/api/v1/db/memberships")).json()
    assert listing["memberships"][0]["rcon_sync_status"] == "FAILED"
    second = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert second.json()["replayed"] is True
    assert second.json()["warcon"]["status"] == "SUCCESS"
    assert len((await session.exec(select(Membership))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"membership_type": "VIP_EXPRESS"}, {"server_id": 5}, {"role_granted_id": 99},
])
async def test_invalid_discord_creation_does_not_save(client, session, discord_player, delivery, changes):
    response = await client.post("/api/v1/db/players/membership", json=command_payload(**changes))
    assert response.status_code == 400
    assert (await session.exec(select(Membership))).all() == []
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_role_is_rejected_before_save(client, session, discord_player, delivery):
    _, membership_type, _ = discord_player
    membership_type.role_id = None
    session.add(membership_type)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "membership_type_role_missing"}
    assert (await session.exec(select(PlayerRole))).all() == []
    assert (await session.exec(select(Membership))).all() == []
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_warcon_configuration_is_rejected_before_save(client, session, discord_player, delivery, warcon_settings):
    warcon_settings.WARCON_API_TOKEN = ""
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 503
    assert (await session.exec(select(Membership))).all() == []


@pytest.mark.asyncio
async def test_discord_creation_requires_operation_identifier(client, session, discord_player, delivery):
    payload = command_payload()
    del payload["operation_id"]
    response = await client.post("/api/v1/db/players/membership", json=payload)
    assert response.status_code == 422
    assert (await session.exec(select(Membership))).all() == []


@pytest.mark.asyncio
async def test_legacy_creation_does_not_call_warcon(client, session, discord_player, delivery):
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": "76561198000000001", "membership_type": "VIP_LEGACY", "days": 2,
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["warcon"] is None
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_expiry_maintenance_does_not_overwrite_warcon_slots(session, discord_player, warcon_settings, monkeypatch):
    player, _, role = discord_player
    expired = Membership(steam_id=player.steam_id, membership_type="EXPRESS", role_granted_id=role.id,
                         end_time=datetime.now(timezone.utc) - timedelta(days=1), rcon_sync_status="FAILED")
    session.add(expired)
    await session.commit()
    direct_sync = AsyncMock()
    monkeypatch.setattr(RCONManager, "get_all_active_servers", direct_sync)
    await MembershipsService.sync_memberships_logic(session)
    await session.refresh(expired)
    assert expired.is_active is False
    assert expired.rcon_sync_status == "FAILED"
    direct_sync.assert_not_awaited()


def applied_sync():
    return {"serverId": "test-server", "ok": True, "pending": False, "failed": 0}


@pytest.mark.asyncio
async def test_warcon_public_api_creation_sets_discord_notes_expiry_and_checks_game(warcon_settings, monkeypatch):
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    requests = AsyncMock(return_value=(201, {"ok": True, "entry": {"id": "entry-1"},
                                           "sync": {"servers": [applied_sync()]}}))
    monkeypatch.setattr(WarconClient, "_request", requests)
    result = await WarconClient().upsert_reserved_slot("76561198000000001", 42, "VIP Express", expiry)
    assert result.status == "SUCCESS"
    args = requests.await_args.args
    assert args[1:3] == ("POST", "/api/orgs/test-org/lists/reserve/entries")
    assert args[3] == {"steamId": "76561198000000001", "reason": "VIP Express | Discord | ID:#42",
                       "expiresAt": expiry.isoformat()}


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_note", [
    "Discord | membership:#1 | type:EXPRESS",
    "Discord | membership:#1 | VIP Express",
    "VIP Express | Discord | ID:#1",
])
async def test_warcon_retry_updates_own_entry_without_delete_then_applies(warcon_settings, monkeypatch, existing_note):
    requests = AsyncMock(side_effect=[
        (409, {"error": {"code": "duplicate"}}),
        (200, {"ok": True, "entries": [{"id": "entry-1", "steamId": "steam-1", "reason": existing_note}]}),
        (200, {"ok": True, "entry": {"steamId": "steam-1"}}),
        (200, {"ok": True, "sync": applied_sync()}),
    ])
    monkeypatch.setattr(WarconClient, "_request", requests)
    result = await WarconClient().upsert_reserved_slot("steam-1", 2, "VIP Permanente", None)
    assert result.status == "SUCCESS" and result.entry_id == "entry-1"
    assert [call.args[1] for call in requests.await_args_list] == ["POST", "GET", "PATCH", "POST"]
    assert requests.await_args_list[2].args[-1]["expiresAt"] is None
    assert requests.await_args_list[2].args[-1]["reason"] == "VIP Permanente | Discord | ID:#2"
    assert requests.await_args_list[3].args[2] == "/api/servers/test-server/lists/sync"


@pytest.mark.asyncio
@pytest.mark.parametrize("manual_note", [
    "Staff", "VIP Normal", "VIP Normal | Discord", "VIP Normal | Discord | ID:#invalid",
    "VIP Normal | Discord | ID:#1 | Staff", " | Discord | ID:#1",
    "VIP Normal | Discord | ID:#١",
])
async def test_warcon_manual_entry_is_preserved(warcon_settings, monkeypatch, manual_note):
    requests = AsyncMock(side_effect=[
        (409, {"error": {"code": "duplicate"}}),
        (200, {"ok": True, "entries": [{"id": "manual", "steamId": "steam-1", "reason": manual_note}]}),
    ])
    monkeypatch.setattr(WarconClient, "_request", requests)
    result = await WarconClient().upsert_reserved_slot("steam-1", 2, "EXPRESS", None)
    assert result.status == "FAILED"
    assert "no fue creado por Discord" in result.error
    assert requests.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["VIP Normal", "VIP " + "ñ" * 250])
async def test_warcon_notes_put_human_name_first_and_preserve_discord_id_within_limit(warcon_settings, monkeypatch, name):
    requests = AsyncMock(return_value=(201, {"ok": True, "entry": {"id": "entry-50"},
                                           "sync": {"servers": [applied_sync()]}}))
    monkeypatch.setattr(WarconClient, "_request", requests)
    result = await WarconClient().upsert_reserved_slot("steam-1", 50, name, None)
    assert result.status == "SUCCESS"
    suffix = " | Discord | ID:#50"
    note = requests.await_args.args[3]["reason"]
    assert note == name[:200 - len(suffix)] + suffix
    assert len(note) <= 200
    assert WarconClient._is_discord_note(note)


@pytest.mark.asyncio
@pytest.mark.parametrize("sync", [
    {"serverId": "test-server", "ok": True, "pending": True, "failed": 0},
    {"serverId": "test-server", "ok": True, "pending": False, "failed": 1},
    {"serverId": "other-server", "ok": True, "pending": False, "failed": 0},
])
async def test_warcon_persistence_alone_is_not_reported_as_delivery(warcon_settings, monkeypatch, sync):
    requests = AsyncMock(return_value=(201, {"ok": True, "entry": {"id": "entry-1"}, "sync": {"servers": [sync]}}))
    monkeypatch.setattr(WarconClient, "_request", requests)
    result = await WarconClient().upsert_reserved_slot("steam-1", 2, "EXPRESS", None)
    assert result.status == "FAILED"
    assert result.entry_id == "entry-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("discord_id", [None, "invalid", "0", "001", "18446744073709551616", "1" * 5000])
async def test_invalid_linked_discord_id_is_rejected_before_creation(client, session, discord_player, delivery, discord_id):
    player = discord_player[0]
    player.discord_id = discord_id
    session.add(player)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 400
    assert (await session.exec(select(Membership))).all() == []
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_after_discord_unlink_does_not_contact_warcon(client, session, discord_player, delivery):
    first = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert first.status_code == 200
    player = discord_player[0]
    player.discord_id = None
    session.add(player)
    await session.commit()
    replay = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert replay.status_code == 409
    assert len((await session.exec(select(Membership))).all()) == 1
    assert delivery.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"ok": True, "entry": None, "sync": {"servers": [applied_sync()]}},
    {"ok": True, "entry": {"id": 123}, "sync": {"servers": [applied_sync()]}},
    {"ok": True, "entry": {"id": "entry-1"}, "sync": None},
    {"ok": True, "entry": {"id": "entry-1"}, "sync": {"servers": None}},
    {"ok": True, "entry": {"id": "entry-1"}, "sync": {"servers": [None]}},
    {"ok": True, "entry": {"id": "entry-1"}, "sync": {"servers": "invalid"}},
    {"ok": True, "entry": {"id": "entry-1"}, "sync": {"servers": [{**applied_sync(), "failed": False}]}},
])
async def test_malformed_warcon_creation_returns_controlled_partial_result(warcon_settings, monkeypatch, body):
    monkeypatch.setattr(WarconClient, "_request", AsyncMock(return_value=(201, body)))
    result = await WarconClient().upsert_reserved_slot("steam-1", 2, "EXPRESS", None)
    assert result.status == "FAILED"
    assert result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("entries", [None, "invalid", [None], [{"steamId": "steam-1", "reason": "Discord | membership:#1", "id": 1}]])
async def test_malformed_warcon_duplicate_listing_is_controlled(warcon_settings, monkeypatch, entries):
    requests = AsyncMock(side_effect=[
        (409, {"error": {"code": "duplicate"}}), (200, {"ok": True, "entries": entries}),
    ])
    monkeypatch.setattr(WarconClient, "_request", requests)
    result = await WarconClient().upsert_reserved_slot("steam-1", 2, "EXPRESS", None)
    assert result.status == "FAILED"
    assert result.error == "Warcon devolvió una respuesta inválida."
    assert requests.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("sync", [None, {**applied_sync(), "serverId": "wrong-server"}])
async def test_warcon_duplicate_sync_must_confirm_target_server(warcon_settings, monkeypatch, sync):
    requests = AsyncMock(side_effect=[
        (409, {"error": {"code": "duplicate"}}),
        (200, {"ok": True, "entries": [{"id": "entry-1", "steamId": "steam-1", "reason": "Discord | membership:#1"}]}),
        (200, {"ok": True}), (200, {"ok": True, "sync": sync}),
    ])
    monkeypatch.setattr(WarconClient, "_request", requests)
    result = await WarconClient().upsert_reserved_slot("steam-1", 2, "EXPRESS", None)
    assert result.status == "FAILED"
    assert result.entry_id == "entry-1"


@pytest.mark.asyncio
async def test_stale_membership_is_revalidated_after_another_session_renews(client, session, test_engine, discord_player, delivery):
    from fastapi import HTTPException
    from sqlmodel.ext.asyncio.session import AsyncSession

    await client.post("/api/v1/db/players/membership", json=command_payload())
    original = (await session.exec(select(Membership))).one()
    async with AsyncSession(test_engine, expire_on_commit=False) as other:
        saved = await other.get(Membership, original.id)
        saved.is_active = False
        other.add(saved)
        await other.commit()
    assert original.is_active is True
    with pytest.raises(HTTPException) as error:
        await MembershipsService._deliver_discord_membership(original, discord_player[0], session, replayed=True)
    assert error.value.status_code == 409
    assert original.is_active is False
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_stale_player_link_is_refreshed_before_delivery(client, session, test_engine, discord_player, delivery):
    from fastapi import HTTPException
    from sqlmodel.ext.asyncio.session import AsyncSession

    await client.post("/api/v1/db/players/membership", json=command_payload())
    original = (await session.exec(select(Membership))).one()
    player = discord_player[0]
    async with AsyncSession(test_engine, expire_on_commit=False) as other:
        saved = await other.get(Player, player.steam_id)
        saved.discord_id = None
        other.add(saved)
        await other.commit()
    assert player.discord_id is not None
    with pytest.raises(HTTPException) as error:
        await MembershipsService._deliver_discord_membership(original, player, session, replayed=True)
    assert error.value.status_code == 409
    assert player.discord_id is None
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_expired_membership_does_not_consume_a_quota_slot(client, session, discord_player, delivery):
    membership_type = discord_player[1]
    membership_type.max_quota = 1
    other_player = Player(steam_id="76561198000000002")
    session.add_all([membership_type, other_player])
    await session.flush()
    session.add(Membership(steam_id=other_player.steam_id, membership_type="EXPRESS",
                           end_time=datetime.now(timezone.utc) - timedelta(days=1)))
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 200
    assert (await client.get("/api/v1/membership-types")).json()[0]["current_usage"] == 1
    assert delivery.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [10**30, 4000000])
async def test_legacy_creation_rejects_date_overflow_without_persisting(client, session, discord_player, delivery, days):
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": discord_player[0].steam_id, "membership_type": "EXPRESS", "days": days,
    })
    assert response.status_code == 400
    assert (await session.exec(select(Membership))).all() == []
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_renewal_rejects_accumulated_date_overflow_without_deactivating(client, session, discord_player, delivery):
    original = Membership(steam_id=discord_player[0].steam_id, membership_type="EXPRESS",
                          end_time=datetime(9999, 12, 30, tzinfo=timezone.utc))
    session.add(original)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": discord_player[0].steam_id, "membership_type": "EXPRESS", "days": 7,
    })
    assert response.status_code == 400
    assert original.is_active is True
    assert len((await session.exec(select(Membership))).all()) == 1
    delivery.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://[invalid", "http://warcon:bad", "http://warcon:65536"])
async def test_malformed_warcon_url_is_controlled_before_save(client, session, discord_player, delivery, warcon_settings, url):
    warcon_settings.WARCON_URL = url
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 503
    assert (await session.exec(select(Membership))).all() == []
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_special_role_is_rejected_before_membership_foreign_key_write(client, session, discord_player, delivery):
    response = await client.post("/api/v1/db/players/membership", json=command_payload(special_role_id=99999))
    assert response.status_code == 400
    assert (await session.exec(select(Membership))).all() == []
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_rejects_active_membership_before_invalid_explicit_special_role(client, session, discord_player, delivery):
    await client.post("/api/v1/db/players/membership", json=command_payload())
    original = (await session.exec(select(Membership))).one()
    special = Role(code="BAD_SPECIAL", name="Bad special", role_type="SPECIAL", discord_role_id="invalid")
    session.add(special)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload(
        operation_id="renewal-with-invalid-special", special_role_id=special.id))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "membership_already_active"}
    assert original.is_active is True
    assert len((await session.exec(select(Membership))).all()) == 1
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_missing_legacy_discord_role_reports_configuration_error_before_save(client, session, discord_player, delivery):
    role = discord_player[2]
    role.discord_role_id = None
    session.add(role)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=command_payload())
    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "membership_role_configuration_missing"}
    assert (await session.exec(select(Membership))).all() == []
    assert (await session.exec(select(PlayerRole))).all() == []
    delivery.assert_not_awaited()
