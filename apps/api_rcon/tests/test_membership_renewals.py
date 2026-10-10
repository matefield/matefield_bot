"""Scheduled periods preserve current benefits and deliver role transitions durably."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import (
    Membership, MembershipRenewalDelivery, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding,
)
from src.modules.v1.services import membership_renewals_service as renewals_module
from src.modules.v1.services import memberships_service as memberships_module
from src.modules.v1.services.memberships_service import MembershipsService
from src.modules.v1.services.membership_renewals_service import MembershipRenewalsService
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import MembershipWarconDelivery

STEAM = "76561198000000091"
USER = "111111111111111111"
GUILD = "222222222222222222"
OTHER_GUILD = "222222222222222223"
ACTOR = "333333333333333333"
OLD_ROLE = "444444444444444444"
NEW_ROLE = "444444444444444445"
BADGE = "444444444444444446"
RENEW_URL = "/api/v1/db/players/membership/renew"
DELIVERIES_URL = "/api/v1/discord/membership-renewals/deliveries"


def payload(**overrides):
    return {"steam_id": STEAM, "membership_type": "regular", "operation_id": "renew-1",
            "guild_id": GUILD, "actor_id": ACTOR, **overrides}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def freeze(monkeypatch, moment):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)
    monkeypatch.setattr(renewals_module, "datetime", Frozen)
    monkeypatch.setattr(memberships_module, "datetime", Frozen)


@pytest.fixture
def deliveries_mock(monkeypatch):
    settings = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    for key, value in {"WARCON_URL": "http://warcon.test", "WARCON_ORG_ID": "org", "WARCON_SERVER_ID": "game", "WARCON_API_TOKEN": "test"}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(ENVIRONMENT_SETTINGS.SECURITY_SETTINGS, "DISCORD_GUILD_IDS", f"{GUILD},{OTHER_GUILD}")
    result = MembershipWarconDelivery(status="SUCCESS", server_id="game", entry_id="entry")
    upsert = AsyncMock(return_value=result)
    remove = AsyncMock(return_value=result)
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", upsert)
    monkeypatch.setattr(WarconClient, "remove_reserved_slot", remove)
    return upsert, remove


@pytest_asyncio.fixture
async def renewal_player(session):
    player = Player(steam_id=STEAM, discord_id=USER)
    old_role = Role(code="EXPRESS", name="VIP Express", role_type="VIP")
    new_role = Role(code="REGULAR", name="VIP Normal", role_type="VIP")
    badge = Role(code="FOUNDER", name="Fundador", role_type="SPECIAL")
    session.add_all([player, old_role, new_role, badge])
    await session.flush()
    for role, physical in [(old_role, OLD_ROLE), (new_role, NEW_ROLE), (badge, BADGE)]:
        session.add(RoleDiscordBinding(role_id=role.id, guild_id=GUILD, discord_role_id=physical, configured_by=ACTOR))
    session.add_all([
        MembershipType(code="express", name="VIP Express", default_days=14, role_id=old_role.id),
        MembershipType(code="regular", name="VIP Normal", default_days=30, role_id=new_role.id),
        PlayerRole(steam_id=STEAM, role_id=old_role.id), PlayerRole(steam_id=STEAM, role_id=badge.id),
    ])
    now = datetime.now(timezone.utc)
    current = Membership(steam_id=STEAM, membership_type="express", start_time=now - timedelta(days=3),
                         end_time=now + timedelta(days=11), role_granted_id=old_role.id,
                         special_role_id=badge.id, discord_guild_id=GUILD, rcon_sync_status="SUCCESS")
    session.add(current)
    await session.commit()
    return player, current, old_role, new_role, badge


@pytest.mark.asyncio
async def test_renewal_creates_next_period_without_altering_current_membership_or_roles(client, session, renewal_player, deliveries_mock):
    _, current, old_role, new_role, badge = renewal_player
    original_end = utc(current.end_time)
    response = await client.post(RENEW_URL, json=payload())
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "SCHEDULED" and result["previous_membership_id"] == current.id
    assert result["discord"] == {"user_id": USER, "guild_id": GUILD, "role_ids": []}
    assert result["membership"]["type_name"] == "VIP Normal"
    future = (await session.exec(select(Membership).where(Membership.id != current.id))).one()
    await session.refresh(current)
    assert current.is_active and utc(current.end_time) == original_end
    assert future.is_active is False and future.is_scheduled is True
    assert utc(future.start_time) == original_end
    assert utc(future.end_time) == original_end + timedelta(days=30)
    assert future.discord_guild_id == GUILD
    assert await session.get(PlayerRole, (STEAM, old_role.id)) is not None
    assert await session.get(PlayerRole, (STEAM, new_role.id)) is None
    assert await session.get(PlayerRole, (STEAM, badge.id)) is not None
    deliveries_mock[0].assert_awaited_once_with(STEAM, future.id, "VIP Normal", utc(future.end_time))
    assert (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json() == {"deliveries": []}
    assert deliveries_mock[0].await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("permanent", [False, True])
async def test_add_rejects_any_existing_active_type_with_controlled_code(client, session, renewal_player, deliveries_mock, permanent):
    current = renewal_player[1]
    if permanent:
        current.end_time = None
        session.add(current)
        await session.commit()
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": STEAM, "membership_type": "regular", "source": "DISCORD", "guild_id": GUILD, "operation_id": "add-new",
    })
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "membership_already_active"}
    assert len((await session.exec(select(Membership))).all()) == 1
    deliveries_mock[0].assert_not_awaited()


@pytest.mark.asyncio
async def test_renewal_replay_does_not_add_another_period_and_conflicting_input_is_rejected(client, session, renewal_player, deliveries_mock):
    first = (await client.post(RENEW_URL, json=payload(days=14))).json()
    second = (await client.post(RENEW_URL, json=payload(days=14))).json()
    assert second["replayed"] is True and second["membership"] == first["membership"]
    conflict = await client.post(RENEW_URL, json=payload(days=15))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "membership_renewal_operation_conflict"
    pending = await client.post(RENEW_URL, json=payload(operation_id="renew-2"))
    assert pending.status_code == 409
    assert pending.json()["detail"]["code"] == "membership_renewal_already_scheduled"
    assert len((await session.exec(select(Membership))).all()) == 2
    assert len((await session.exec(select(MembershipRenewalDelivery))).all()) == 2
    assert deliveries_mock[0].await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,code,status", [("expired", "membership_renewal_not_found", 404), ("permanent", "membership_renewal_permanent", 409), ("duplicate", "membership_renewal_ambiguous", 409), ("other_guild", "membership_renewal_other_guild", 409)])
async def test_invalid_current_membership_is_rejected_without_scheduling(client, session, renewal_player, deliveries_mock, mode, code, status):
    current = renewal_player[1]
    if mode == "expired":
        current.end_time = datetime.now(timezone.utc) - timedelta(days=1)
    elif mode == "permanent":
        current.end_time = None
    elif mode == "other_guild":
        current.discord_guild_id = OTHER_GUILD
    else:
        session.add(Membership(steam_id=STEAM, membership_type="regular"))
    session.add(current)
    await session.commit()
    before = len((await session.exec(select(Membership))).all())
    response = await client.post(RENEW_URL, json=payload())
    assert response.status_code == status and response.json()["detail"]["code"] == code
    assert len((await session.exec(select(Membership))).all()) == before
    deliveries_mock[0].assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_membership_adopts_invoking_guild_once(client, session, renewal_player, deliveries_mock):
    current = renewal_player[1]
    current.discord_guild_id = None
    session.add(current)
    await session.commit()
    assert (await client.post(RENEW_URL, json=payload())).status_code == 200
    await session.refresh(current)
    assert current.discord_guild_id == GUILD


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [-1, True, 3653])
async def test_invalid_explicit_duration_is_schema_validation(client, session, renewal_player, deliveries_mock, days):
    response = await client.post(RENEW_URL, json=payload(days=days))
    assert response.status_code == 422
    assert len((await session.exec(select(Membership))).all()) == 1
    deliveries_mock[0].assert_not_awaited()


@pytest.mark.asyncio
async def test_accumulated_ten_year_limit_is_controlled_before_scheduling(client, session, renewal_player, deliveries_mock):
    current = renewal_player[1]
    current.end_time = datetime.now(timezone.utc) + timedelta(days=3650)
    session.add(current)
    await session.commit()
    response = await client.post(RENEW_URL, json=payload())
    assert response.status_code == 400 and response.json()["detail"]["code"] == "membership_renewal_limit_exceeded"
    deliveries_mock[0].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_temporal_current_can_schedule_a_permanent_next_period(client, session, renewal_player, deliveries_mock, explicit):
    if not explicit:
        regular = (await session.exec(select(MembershipType).where(MembershipType.code == "regular"))).one()
        regular.default_days = 0
        session.add(regular)
        await session.commit()
    response = await client.post(RENEW_URL, json=payload(**({"days": 0} if explicit else {})))
    assert response.status_code == 200 and response.json()["membership"]["end_date"] is None
    current = renewal_player[1]
    future = await session.get(Membership, response.json()["membership"]["id"])
    assert future.is_scheduled and not future.is_active and utc(future.start_time) == utc(current.end_time)
    assert deliveries_mock[0].await_args.args[-1] is None


@pytest.mark.asyncio
async def test_future_memberships_reserve_new_type_quota_and_guard_role_configuration(client, session, renewal_player, deliveries_mock):
    regular = (await session.exec(select(MembershipType).where(MembershipType.code == "regular"))).one()
    regular.max_quota = 1
    session.add(regular)
    await session.commit()
    assert (await client.post(RENEW_URL, json=payload())).status_code == 200
    unassign = await client.request("DELETE", f"/api/v1/discord/guilds/{GUILD}/membership-types/regular/role", json={"actor_id": ACTOR})
    assert unassign.status_code == 409 and unassign.json()["detail"]["code"] == "membership_role_in_use"
    other = Player(steam_id="76561198000000092", discord_id="111111111111111112")
    session.add(other)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": other.steam_id, "membership_type": "regular", "source": "DISCORD", "guild_id": GUILD, "operation_id": "other-add",
    })
    assert response.status_code == 400
    assert len((await session.exec(select(Membership))).all()) == 2


@pytest.mark.asyncio
async def test_due_renewal_transitions_roles_then_requires_acknowledgement(client, session, renewal_player, deliveries_mock, monkeypatch):
    _, current, old_role, new_role, badge = renewal_player
    result = (await client.post(RENEW_URL, json=payload())).json()
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    response = await client.get(DELIVERIES_URL, params={"guild_id": GUILD})
    assert response.status_code == 200
    entry = response.json()["deliveries"][0]
    assert entry["steam_id"] == STEAM and entry["membership_id"] == result["membership"]["id"]
    assert entry["previous_membership_id"] == current.id
    assert entry["role_ids_to_add"] == [NEW_ROLE, BADGE]
    assert entry["role_ids_to_remove"] == [OLD_ROLE]
    await session.refresh(current)
    future = await session.get(Membership, entry["membership_id"])
    assert not current.is_active and future.is_active and not future.is_scheduled
    assert await session.get(PlayerRole, (STEAM, old_role.id)) is None
    assert await session.get(PlayerRole, (STEAM, new_role.id)) is not None
    assert await session.get(PlayerRole, (STEAM, badge.id)) is not None
    assert (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"] == [entry]
    complete_url = f"{DELIVERIES_URL}/{entry['id']}/complete"
    completed = await client.post(complete_url, json={"guild_id": GUILD, "user_id": USER})
    assert completed.status_code == 200 and completed.json() == {"ok": True, "id": entry["id"]}
    assert (await client.post(complete_url, json={"guild_id": GUILD})).status_code == 200
    assert (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json() == {"deliveries": []}


@pytest.mark.asyncio
async def test_same_role_continuity_never_schedules_role_removal(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    assert (await client.post(RENEW_URL, json=payload(membership_type="express"))).status_code == 200
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    entry = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    assert entry["role_ids_to_add"] == [OLD_ROLE, BADGE]
    assert entry["role_ids_to_remove"] == []
    assert await session.get(PlayerRole, (STEAM, renewal_player[2].id)) is not None


@pytest.mark.asyncio
async def test_partial_warcon_failure_is_saved_and_maintenance_retries_without_rescheduling(client, session, renewal_player, deliveries_mock):
    upsert = deliveries_mock[0]
    upsert.return_value = MembershipWarconDelivery(status="FAILED", server_id="game", error="safe failure")
    response = await client.post(RENEW_URL, json=payload())
    assert response.status_code == 200 and response.json()["warcon"]["status"] == "FAILED"
    future_id = response.json()["membership"]["id"]
    upsert.return_value = MembershipWarconDelivery(status="SUCCESS", server_id="game", entry_id="entry")
    assert (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json() == {"deliveries": []}
    assert upsert.await_count == 1
    await MembershipRenewalsService.retry_pending(session.bind)
    future = await session.get(Membership, future_id)
    await session.refresh(future)
    assert future.rcon_sync_status == "SUCCESS" and future.is_scheduled
    assert len((await session.exec(select(Membership))).all()) == 2
    assert upsert.await_count == 2


@pytest.mark.asyncio
async def test_removal_cancels_current_and_scheduled_period_without_later_role_activation(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    future = (await client.post(RENEW_URL, json=payload())).json()["membership"]
    response = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={
        "operation_id": "remove-1", "guild_id": GUILD, "actor_id": ACTOR,
    })
    assert response.status_code == 200
    assert response.json()["removed_membership_ids"] == [current.id, future["id"]]
    rows = (await session.exec(select(Membership))).all()
    assert all(not row.is_active and not row.is_scheduled for row in rows)
    assert all(receipt.cancelled for receipt in (await session.exec(select(MembershipRenewalDelivery))).all())
    freeze(monkeypatch, utc(current.end_time) + timedelta(days=1))
    assert (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json() == {"deliveries": []}
    replay = await client.post(RENEW_URL, json=payload())
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "membership_renewal_cancelled"


@pytest.mark.asyncio
async def test_pending_role_delivery_blocks_domain_mutations_until_ack(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    await client.post(RENEW_URL, json=payload())
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    entry = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    attempts = [
        ("post", RENEW_URL, payload(operation_id="renew-2")),
        ("post", f"/api/v1/db/players/{STEAM}/membership/remove", {"operation_id": "remove-1", "guild_id": GUILD, "actor_id": ACTOR}),
        ("post", "/api/v1/db/players/membership", {"steam_id": STEAM, "membership_type": "regular", "source": "DISCORD", "guild_id": GUILD, "operation_id": "new-add"}),
        ("put", f"/api/v1/db/memberships/{entry['membership_id']}", {"add_days": 1}),
        ("post", "/api/v1/db/memberships/compensate", {"days": 1}),
    ]
    for method, url, data in attempts:
        response = await client.request(method.upper(), url, json=data)
        assert response.status_code == 409, (url, response.text)
        assert response.json()["detail"]["code"] == "membership_renewal_delivery_pending"
    assert (await client.post(f"{DELIVERIES_URL}/{entry['id']}/complete", json={"guild_id": GUILD})).status_code == 200
    assert (await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={"operation_id": "remove-2", "guild_id": GUILD, "actor_id": ACTOR})).status_code == 200


@pytest.mark.asyncio
async def test_scheduled_period_guards_legacy_date_mutations(client, session, renewal_player, deliveries_mock):
    current = renewal_player[1]
    await client.post(RENEW_URL, json=payload())
    for method, url, data in [
        ("PUT", f"/api/v1/db/memberships/{current.id}", {"add_days": 1}),
        ("POST", "/api/v1/db/memberships/compensate", {"days": 1}),
        ("DELETE", f"/api/v1/db/memberships/{current.id}", None),
        ("POST", "/api/v1/db/players/membership", {"steam_id": STEAM, "membership_type": "express", "days": 1}),
    ]:
        response = await client.request(method, url, json=data)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_renewals_pending"
    await session.refresh(current)
    future = (await session.exec(select(Membership).where(Membership.is_scheduled == True))).one()
    assert utc(current.end_time) == utc(future.start_time)


@pytest.mark.asyncio
async def test_long_outage_does_not_activate_expired_next_period_or_leave_old_vip_delivery(client, session, renewal_player, deliveries_mock, monkeypatch):
    result = (await client.post(RENEW_URL, json=payload(days=1))).json()
    end = datetime.fromisoformat(result["membership"]["end_date"].replace("Z", "+00:00"))
    freeze(monkeypatch, end + timedelta(days=1))
    entry = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    assert NEW_ROLE not in entry["role_ids_to_add"] and OLD_ROLE not in entry["role_ids_to_add"]
    assert set(entry["role_ids_to_remove"]) == {OLD_ROLE, NEW_ROLE}
    future = await session.get(Membership, result["membership"]["id"])
    assert not future.is_active and not future.is_scheduled
    assert await session.get(PlayerRole, (STEAM, renewal_player[2].id)) is None
    assert await session.get(PlayerRole, (STEAM, renewal_player[3].id)) is None


@pytest.mark.asyncio
async def test_delivery_scope_identity_and_readiness_are_validated(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    await client.post(RENEW_URL, json=payload())
    receipt = (await session.exec(select(MembershipRenewalDelivery).where(MembershipRenewalDelivery.phase == "START"))).one()
    complete_url = f"{DELIVERIES_URL}/{receipt.id}/complete"
    assert (await client.post(complete_url, json={"guild_id": GUILD})).status_code == 409
    assert (await client.get(DELIVERIES_URL, params={"guild_id": OTHER_GUILD})).json() == {"deliveries": []}
    assert (await client.post(complete_url, json={"guild_id": OTHER_GUILD})).status_code == 404
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    assert len((await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"]) == 1
    assert (await client.post(complete_url, json={"guild_id": GUILD, "user_id": ACTOR})).status_code == 409
    assert (await client.post(complete_url, json={"guild_id": GUILD, "user_id": USER})).status_code == 200
    assert (await client.get(DELIVERIES_URL, params={"guild_id": "0"})).status_code == 422


@pytest.mark.asyncio
async def test_membership_read_exposes_scheduled_state_and_maintenance_activates_before_expiring(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    result = (await client.post(RENEW_URL, json=payload(membership_type="express"))).json()
    rows = (await client.get("/api/v1/db/memberships", params={"discord_id": USER, "guild_id": GUILD})).json()["memberships"]
    assert rows[0]["id"] == current.id and rows[0]["is_scheduled"] is False
    assert rows[1]["id"] == result["membership"]["id"] and rows[1]["is_scheduled"] is True
    freeze(monkeypatch, utc(current.end_time))
    await MembershipsService.sync_memberships_logic(session)
    future = await session.get(Membership, result["membership"]["id"])
    assert future.is_active and not future.is_scheduled
    assert await session.get(PlayerRole, (STEAM, renewal_player[2].id)) is not None


@pytest.mark.asyncio
async def test_completed_start_receipt_does_not_acknowledge_later_expiration(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    result = (await client.post(RENEW_URL, json=payload(days=1))).json()
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    start = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    assert (await client.post(f"{DELIVERIES_URL}/{start['id']}/complete", json={"guild_id": GUILD})).status_code == 200
    end = datetime.fromisoformat(result["membership"]["end_date"].replace("Z", "+00:00"))
    freeze(monkeypatch, end)
    expiration = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    assert expiration["id"] != start["id"] and expiration["membership_id"] == start["membership_id"]
    assert expiration["role_ids_to_add"] == [] and expiration["role_ids_to_remove"] == [NEW_ROLE]
    assert BADGE not in expiration["role_ids_to_remove"]
    assert (await client.post(f"{DELIVERIES_URL}/{start['id']}/complete", json={"guild_id": GUILD})).status_code == 200
    assert (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"] == [expiration]
    assert (await client.post(f"{DELIVERIES_URL}/{expiration['id']}/complete", json={"guild_id": GUILD})).status_code == 200
    assert (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json() == {"deliveries": []}
    assert await session.get(PlayerRole, (STEAM, renewal_player[3].id)) is None
    assert await session.get(PlayerRole, (STEAM, renewal_player[4].id)) is not None


@pytest.mark.asyncio
async def test_completed_start_blocks_legacy_calendar_edits_until_renewed_period_ends(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    future = (await client.post(RENEW_URL, json=payload())).json()["membership"]
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    entry = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    await client.post(f"{DELIVERIES_URL}/{entry['id']}/complete", json={"guild_id": GUILD})
    response = await client.put(f"/api/v1/db/memberships/{future['id']}", json={"add_days": 1})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_renewals_pending"
    response = await client.post("/api/v1/db/memberships/compensate", json={"days": 1})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_renewals_pending"


@pytest.mark.asyncio
async def test_add_rejects_due_future_before_activation_instead_of_creating_overlap(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    await client.post(RENEW_URL, json=payload())
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": STEAM, "membership_type": "regular", "source": "DISCORD", "guild_id": GUILD, "operation_id": "add-overlap",
    })
    assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_renewal_already_scheduled"
    assert len((await session.exec(select(Membership))).all()) == 2
    assert deliveries_mock[0].await_count == 1


@pytest.mark.asyncio
async def test_remove_from_another_guild_cannot_cancel_known_owner_membership(client, session, renewal_player, deliveries_mock):
    await client.post(RENEW_URL, json=payload())
    response = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={
        "operation_id": "wrong-guild-remove", "guild_id": OTHER_GUILD, "actor_id": ACTOR,
    })
    assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_removal_other_guild"
    deliveries_mock[1].assert_not_awaited()
    assert (await session.exec(select(Membership).where(Membership.is_scheduled == True))).one().is_scheduled


@pytest.mark.asyncio
async def test_account_ownership_cannot_change_during_future_or_active_renewal(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    await client.post(RENEW_URL, json=payload())
    for url, method, data in [
        ("/api/v1/db/players/unlink", "POST", {"discord_id": USER}),
        (f"/api/v1/db/players/{STEAM}", "PUT", {"discord_id": ACTOR}),
        (f"/api/v1/db/players/{STEAM}", "PUT", {"discord_id": ""}),
    ]:
        response = await client.request(method, url, json=data)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_renewals_pending"
    assert (await client.put(f"/api/v1/db/players/{STEAM}", json={"observations": "Updated note", "discord_id": USER})).status_code == 200
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    entry = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    assert (await client.post("/api/v1/db/players/unlink", json={"discord_id": USER})).json()["detail"]["code"] == "membership_renewal_delivery_pending"
    player = renewal_player[0]
    player.discord_id = ACTOR
    session.add(player)
    await session.commit()
    response = await client.post(f"{DELIVERIES_URL}/{entry['id']}/complete", json={"guild_id": GUILD})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_renewal_delivery_account_changed"


@pytest.mark.asyncio
async def test_expiration_removes_only_delivered_snapshot_not_newly_remapped_role(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    result = (await client.post(RENEW_URL, json=payload(days=1))).json()
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    entry = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    await client.post(f"{DELIVERIES_URL}/{entry['id']}/complete", json={"guild_id": GUILD})
    end = datetime.fromisoformat(result["membership"]["end_date"].replace("Z", "+00:00"))
    freeze(monkeypatch, end + timedelta(seconds=1))
    await MembershipRenewalsService.activate_due(session, GUILD)
    binding = (await session.exec(select(RoleDiscordBinding).where(
        RoleDiscordBinding.guild_id == GUILD, RoleDiscordBinding.role_id == renewal_player[3].id,
    ))).one()
    replacement = "444444444444444449"
    binding.discord_role_id = replacement
    session.add(binding)
    await session.commit()
    expiration = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    assert expiration["role_ids_to_remove"] == [NEW_ROLE]
    assert replacement not in expiration["role_ids_to_remove"]


@pytest.mark.asyncio
async def test_role_shared_with_staff_is_preserved_on_expiration(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    badge_binding = (await session.exec(select(RoleDiscordBinding).where(
        RoleDiscordBinding.guild_id == GUILD, RoleDiscordBinding.role_id == renewal_player[4].id,
    ))).one()
    badge_binding.discord_role_id = NEW_ROLE
    session.add(badge_binding)
    await session.commit()
    result = (await client.post(RENEW_URL, json=payload(days=1))).json()
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    start = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    await client.post(f"{DELIVERIES_URL}/{start['id']}/complete", json={"guild_id": GUILD})
    freeze(monkeypatch, datetime.fromisoformat(result["membership"]["end_date"].replace("Z", "+00:00")))
    expiration = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    assert expiration["role_ids_to_add"] == [] and expiration["role_ids_to_remove"] == []
    assert await session.get(PlayerRole, (STEAM, renewal_player[4].id)) is not None


@pytest.mark.asyncio
async def test_next_renewal_activates_before_prior_expiration_without_same_role_gap(client, session, renewal_player, deliveries_mock, monkeypatch):
    current = renewal_player[1]
    first = (await client.post(RENEW_URL, json=payload(days=1))).json()
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    start = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"][0]
    await client.post(f"{DELIVERIES_URL}/{start['id']}/complete", json={"guild_id": GUILD})
    second = (await client.post(RENEW_URL, json=payload(days=1, operation_id="renew-2"))).json()
    boundary = datetime.fromisoformat(first["membership"]["end_date"].replace("Z", "+00:00"))
    freeze(monkeypatch, boundary)
    entries = (await client.get(DELIVERIES_URL, params={"guild_id": GUILD})).json()["deliveries"]
    assert len(entries) == 2
    assert all(entry["role_ids_to_remove"] == [] for entry in entries)
    assert any(entry["membership_id"] == second["membership"]["id"] and NEW_ROLE in entry["role_ids_to_add"] for entry in entries)
    assert await session.get(PlayerRole, (STEAM, renewal_player[3].id)) is not None
