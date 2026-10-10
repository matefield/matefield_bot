"""Membership messages describe authoritative periods and proven administrative removals."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.connections.databases.db import Membership, MembershipRemovalOperation, MembershipRenewalDelivery, MembershipType
from src.modules.v1.services.membership_state_service import MembershipStateService
from src.modules.v1.services.memberships_service import MembershipsService
from test_membership_deliveries import ADD_URL, QUEUE_URL, initial_player, payload
from test_membership_renewals import (
    ACTOR, GUILD, OTHER_GUILD, STEAM, USER, deliveries_mock, freeze, renewal_player, utc,
)


async def period(session, role, *, active=True, scheduled=False, start_days=-2, end_days=28, guild=GUILD):
    now = datetime.now(timezone.utc)
    membership = Membership(steam_id=STEAM, membership_type="regular", role_granted_id=role.id,
                            start_time=now + timedelta(days=start_days),
                            end_time=now + timedelta(days=end_days) if end_days is not None else None,
                            is_active=active, is_scheduled=scheduled, discord_guild_id=guild)
    session.add(membership)
    await session.commit()
    return membership


async def removal_receipt(session, membership, **overrides):
    result = {
        "ok": True, "steam_id": STEAM, "operation_id": "historical-removal",
        "removed_membership_ids": [membership.id],
        "discord": {"user_id": USER, "guild_id": GUILD, "role_ids": []},
        "warcon": {"status": "SUCCESS", "server_id": "game"},
        **overrides,
    }
    operation = MembershipRemovalOperation(
        operation_id="historical-removal", request_hash="test", steam_id=STEAM, guild_id=GUILD,
        actor_id=ACTOR, user_id=USER, result_json=json.dumps(result), discord_roles_removed=False,
    )
    session.add(operation)
    await session.commit()
    return operation


@pytest.mark.asyncio
@pytest.mark.parametrize("active,scheduled,start_days,end_days,status", [
    (True, False, -2, 28, "ACTIVE"),
    (True, False, -2, None, "ACTIVE"),
    (False, True, 2, 32, "SCHEDULED"),
    (False, True, -2, 28, "ACTIVATION_PENDING"),
    (True, False, 2, 32, "NOT_STARTED"),
    (True, False, -32, -2, "EXPIRED"),
    (False, False, -32, -2, "EXPIRED"),
    (False, True, -32, -2, "EXPIRED"),
    (False, False, -2, 28, "INACTIVE"),
    (False, False, 2, 32, "INACTIVE"),
])
async def test_state_uses_flags_and_utc_dates_without_mutating_rows(session, initial_player, active, scheduled, start_days, end_days, status):
    membership = await period(session, initial_player[2], active=active, scheduled=scheduled, start_days=start_days, end_days=end_days)
    context = (await MembershipStateService.batch([membership], session, GUILD))[membership.id]
    assert context.status == status
    assert context.id == membership.id and context.type_name == "VIP Normal" and context.discord_id == USER
    assert context.start_date.tzinfo == timezone.utc
    assert context.removed_at is None and context.removed_by is None
    await session.refresh(membership)
    assert membership.is_active is active and membership.is_scheduled is scheduled


@pytest.mark.asyncio
async def test_removed_state_requires_successful_receipt_and_precedes_original_expiry(session, initial_player):
    membership = await period(session, initial_player[2], active=False, start_days=-32, end_days=-2)
    operation = await removal_receipt(session, membership)
    context = (await MembershipStateService.batch([membership], session, GUILD))[membership.id]
    assert context.status == "REMOVED"
    assert context.removed_at == utc(operation.created_at) and context.removed_by == ACTOR
    # A pending Discord ACK does not undo the already confirmed DB/Warcon removal.
    assert operation.discord_roles_removed is False
    membership.is_active = True
    membership.end_time = datetime.now(timezone.utc) + timedelta(days=2)
    session.add(membership)
    await session.commit()
    reactivated = (await MembershipStateService.batch([membership], session, GUILD))[membership.id]
    assert reactivated.status == "ACTIVE" and reactivated.removed_at is None and reactivated.removed_by is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"ok": False}, {"operation_id": "another-operation"}, {"steam_id": "76561198000000092"},
    {"removed_membership_ids": [True]}, {"removed_membership_ids": [999999]},
    {"discord": {"user_id": USER, "guild_id": OTHER_GUILD, "role_ids": []}},
    {"warcon": {"status": "FAILED", "server_id": "game"}},
])
async def test_inconsistent_removal_receipt_does_not_invent_a_cancellation(session, initial_player, changes):
    membership = await period(session, initial_player[2], active=False)
    await removal_receipt(session, membership, **changes)
    context = (await MembershipStateService.batch([membership], session, GUILD))[membership.id]
    assert context.status == "INACTIVE" and context.removed_at is None and context.removed_by is None


@pytest.mark.asyncio
async def test_cancelled_expiration_is_not_evidence_of_membership_removal(session, initial_player):
    membership = await period(session, initial_player[2], active=False, end_days=None)
    session.add(MembershipRenewalDelivery(membership_id=membership.id, phase="END", guild_id=GUILD,
                actor_id=ACTOR, user_id=USER, available_at=datetime.now(timezone.utc),
                role_ids_to_add_json="[]", role_ids_to_remove_json="[]", cancelled=True))
    await session.commit()
    context = (await MembershipStateService.batch([membership], session, GUILD))[membership.id]
    assert context.status == "INACTIVE" and context.removed_at is None


@pytest.mark.asyncio
async def test_context_and_removal_actor_respect_guild_visibility(session, initial_player):
    membership = await period(session, initial_player[2], active=False)
    await removal_receipt(session, membership)
    foreign = await MembershipStateService.detail("membership_retry_unavailable", membership, session, OTHER_GUILD)
    assert foreign == {"code": "membership_retry_unavailable"}
    public_state = (await MembershipStateService.batch([membership], session, OTHER_GUILD))[membership.id]
    assert public_state.status == "INACTIVE" and public_state.removed_at is None and public_state.removed_by is None
    # Global legacy records may be described, but another guild's removal metadata remains private.
    membership.discord_guild_id = None
    session.add(membership)
    await session.commit()
    legacy = await MembershipStateService.detail("membership_retry_unavailable", membership, session, OTHER_GUILD)
    assert legacy["membership"]["status"] == "INACTIVE" and legacy["membership"]["removed_by"] is None


@pytest.mark.asyncio
async def test_expired_retry_returns_period_and_never_calls_warcon(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    membership = await session.get(Membership, created["membership"]["id"])
    freeze(monkeypatch, utc(membership.end_time) + timedelta(seconds=1))
    response = await client.post(f"/api/v1/db/memberships/{membership.id}/retry", json={"guild_id": GUILD, "actor_id": ACTOR})
    detail = response.json()["detail"]
    assert response.status_code == 409 and detail["code"] == "membership_retry_unavailable"
    assert detail["membership"]["status"] == "EXPIRED" and detail["membership"]["id"] == membership.id
    assert datetime.fromisoformat(detail["membership"]["start_date"]) == utc(membership.start_time)
    assert datetime.fromisoformat(detail["membership"]["end_date"]) == utc(membership.end_time)
    assert deliveries_mock[0].await_count == 1


@pytest.mark.asyncio
async def test_active_unsupported_retry_has_distinct_code_and_no_false_expiry(client, session, initial_player, deliveries_mock):
    membership = await period(session, initial_player[2])
    response = await client.post(f"/api/v1/db/memberships/{membership.id}/retry", json={"guild_id": GUILD, "actor_id": ACTOR})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_retry_unsupported"
    assert response.json()["detail"]["membership"]["status"] == "ACTIVE"
    deliveries_mock[0].assert_not_awaited()


@pytest.mark.asyncio
async def test_future_retry_reports_not_started_instead_of_granting_a_role(client, session, initial_player, deliveries_mock):
    membership = await period(session, initial_player[2], start_days=2, end_days=32)
    response = await client.post(f"/api/v1/db/memberships/{membership.id}/retry", json={"guild_id": GUILD, "actor_id": ACTOR})
    assert response.status_code == 409 and response.json()["detail"]["membership"]["status"] == "NOT_STARTED"
    deliveries_mock[0].assert_not_awaited()


@pytest.mark.asyncio
async def test_add_and_renew_rejections_include_the_relevant_period(client, session, initial_player, deliveries_mock):
    current = await period(session, initial_player[2], end_days=None)
    add = await client.post(ADD_URL, json=payload())
    assert add.status_code == 409 and add.json()["detail"]["membership"]["id"] == current.id
    assert add.json()["detail"]["membership"]["status"] == "ACTIVE"
    renew = await client.post("/api/v1/db/players/membership/renew", json={"steam_id": STEAM, "membership_type": "regular", "operation_id": "renew-permanent", "guild_id": GUILD, "actor_id": ACTOR})
    assert renew.status_code == 409 and renew.json()["detail"]["code"] == "membership_renewal_permanent"
    assert renew.json()["detail"]["membership"]["id"] == current.id and renew.json()["detail"]["membership"]["end_date"] is None


@pytest.mark.asyncio
async def test_no_current_period_rejections_show_visible_history_only(client, session, initial_player, deliveries_mock):
    expired = await period(session, initial_player[2], active=False, start_days=-32, end_days=-2)
    foreign = await period(session, initial_player[2], active=False, start_days=-1, end_days=29, guild=OTHER_GUILD)
    removal = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={"guild_id": GUILD, "actor_id": ACTOR, "operation_id": "remove-no-active"})
    assert removal.status_code == 404 and removal.json()["detail"]["membership"]["id"] == expired.id
    assert removal.json()["detail"]["membership"]["status"] == "EXPIRED"
    renewal = await client.post("/api/v1/db/players/membership/renew", json={"steam_id": STEAM, "membership_type": "regular", "operation_id": "renew-no-active", "guild_id": GUILD, "actor_id": ACTOR})
    assert renewal.status_code == 404 and renewal.json()["detail"]["membership"]["id"] == expired.id
    assert foreign.id != expired.id


@pytest.mark.asyncio
async def test_successful_removal_saves_confirmed_period_context_for_replay(client, session, initial_player, deliveries_mock):
    created = (await client.post(ADD_URL, json=payload())).json()
    response = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={"guild_id": GUILD, "actor_id": ACTOR, "operation_id": "remove-context"})
    assert response.status_code == 200
    contexts = response.json()["memberships"]
    assert len(contexts) == 1 and contexts[0]["id"] == created["membership"]["id"]
    assert contexts[0]["status"] == "REMOVED" and contexts[0]["removed_by"] == ACTOR and contexts[0]["removed_at"]
    operation = await session.get(MembershipRemovalOperation, "remove-context")
    assert json.loads(operation.result_json)["memberships"] == contexts
    replay = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={"guild_id": GUILD, "actor_id": ACTOR, "operation_id": "remove-context"})
    assert replay.status_code == 200 and replay.json()["memberships"] == contexts


@pytest.mark.asyncio
async def test_personal_and_admin_views_order_current_then_future_then_history(client, session, initial_player, deliveries_mock):
    expired = await period(session, initial_player[2], active=True, start_days=-32, end_days=-2)
    current = await period(session, initial_player[2], active=True)
    future = await period(session, initial_player[2], active=True, start_days=2, end_days=32)
    personal = await client.get("/api/v1/db/memberships", params={"discord_id": USER, "guild_id": GUILD})
    rows = personal.json()["memberships"]
    assert [row["id"] for row in rows] == [current.id, future.id, expired.id]
    assert [row["status"] for row in rows] == ["ACTIVE", "NOT_STARTED", "EXPIRED"]
    administrative = await client.get("/api/v1/db/memberships", params={"guild_id": GUILD})
    assert [row["id"] for row in administrative.json()["memberships"]] == [current.id, future.id, expired.id]
    await session.refresh(expired)
    assert expired.is_active is True


@pytest.mark.asyncio
async def test_invalid_legacy_start_date_does_not_turn_controlled_error_or_list_into_500(client, session, initial_player, deliveries_mock):
    membership = await period(session, initial_player[2], active=False, start_days=-32, end_days=-2)
    membership.start_time = None
    session.add(membership)
    await session.commit()
    response = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={"guild_id": GUILD, "actor_id": ACTOR, "operation_id": "remove-invalid-legacy"})
    assert response.status_code == 404 and response.json()["detail"] == {"code": "membership_removal_not_found"}
    view = await client.get("/api/v1/db/memberships", params={"guild_id": GUILD})
    assert view.status_code == 200
    assert view.json()["memberships"][0]["start_date"] is None
    assert view.json()["memberships"][0]["status"] == "INACTIVE"


@pytest.mark.asyncio
async def test_add_reports_removed_period_when_discord_removal_ack_is_pending(client, session, initial_player, deliveries_mock):
    created = (await client.post(ADD_URL, json=payload())).json()
    removed = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={
        "guild_id": GUILD, "actor_id": ACTOR, "operation_id": "remove-awaiting-ack",
    })
    assert removed.status_code == 200
    response = await client.post(ADD_URL, json={**payload(), "operation_id": "add-after-removal"})
    detail = response.json()["detail"]
    assert response.status_code == 409 and detail["code"] == "membership_removal_pending"
    assert detail["membership"]["id"] == created["membership"]["id"]
    assert detail["membership"]["status"] == "REMOVED" and detail["membership"]["removed_by"] == ACTOR
    assert detail["membership"]["start_date"] == created["membership"]["start_date"]
    assert detail["membership"]["end_date"] == created["membership"]["end_date"]


@pytest.mark.asyncio
async def test_renew_reports_expired_period_when_discord_expiration_ack_is_pending(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    membership = await session.get(Membership, created["membership"]["id"])
    freeze(monkeypatch, utc(membership.end_time) + timedelta(seconds=1))
    pending = await client.get(QUEUE_URL, params={"guild_id": GUILD})
    end_receipt = (await session.exec(select(MembershipRenewalDelivery).where(
        MembershipRenewalDelivery.membership_id == membership.id, MembershipRenewalDelivery.phase == "END",
    ))).one()
    assert [delivery["id"] for delivery in pending.json()["deliveries"]] == [end_receipt.id]
    response = await client.post("/api/v1/db/players/membership/renew", json={
        "steam_id": STEAM, "membership_type": "regular", "operation_id": "renew-expired-awaiting-ack",
        "guild_id": GUILD, "actor_id": ACTOR,
    })
    detail = response.json()["detail"]
    assert response.status_code == 409 and detail["code"] == "membership_renewal_delivery_pending"
    assert detail["membership"]["id"] == membership.id and detail["membership"]["status"] == "EXPIRED"
    assert datetime.fromisoformat(detail["membership"]["end_date"]) == utc(membership.end_time)


@pytest.mark.asyncio
@pytest.mark.parametrize("guild_id", [None, OTHER_GUILD])
async def test_pending_removal_context_does_not_expose_another_guild(session, initial_player, guild_id):
    membership = await period(session, initial_player[2], active=False)
    await removal_receipt(session, membership)
    with pytest.raises(HTTPException) as exception:
        await MembershipsService._require_no_pending_removal(STEAM, session, guild_id=guild_id)
    assert exception.value.detail == {"code": "membership_removal_pending"}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_id", [0, -1, True, 2 ** 256])
async def test_pending_removal_with_invalid_receipt_id_keeps_controlled_error(session, initial_player, invalid_id):
    membership = await period(session, initial_player[2], active=False)
    await removal_receipt(session, membership, removed_membership_ids=[invalid_id])
    with pytest.raises(HTTPException) as exception:
        await MembershipsService._require_no_pending_removal(STEAM, session, guild_id=GUILD)
    assert exception.value.detail == {"code": "membership_removal_pending"}


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [False, True])
async def test_expired_renewal_replay_cannot_write_a_permanent_slot_before_maintenance(client, session, renewal_player, deliveries_mock, monkeypatch, active):
    request = {"steam_id": STEAM, "membership_type": "regular", "operation_id": "renew-late-replay",
               "guild_id": GUILD, "actor_id": ACTOR}
    created = await client.post("/api/v1/db/players/membership/renew", json=request)
    assert created.status_code == 200
    membership = await session.get(Membership, created.json()["membership"]["id"])
    membership.is_active = active
    membership.is_scheduled = not active
    session.add(membership)
    await session.commit()
    original_end = utc(membership.end_time)
    freeze(monkeypatch, original_end + timedelta(seconds=1))
    # Do not poll deliveries or run activation: flags deliberately remain stale.
    response = await client.post("/api/v1/db/players/membership/renew", json=request)
    detail = response.json()["detail"]
    assert response.status_code == 409 and detail["code"] == "membership_renewal_unavailable"
    assert detail["membership"]["id"] == membership.id and detail["membership"]["status"] == "EXPIRED"
    assert deliveries_mock[0].await_count == 1
    await session.refresh(membership)
    assert membership.is_active is active and membership.is_scheduled is not active
    assert utc(membership.end_time) == original_end


@pytest.mark.asyncio
async def test_missing_catalog_name_is_optional_without_losing_removed_period_context(session, initial_player):
    membership = await period(session, initial_player[2], active=False)
    membership.membership_type = "LEGACY"
    session.add(membership)
    await session.commit()
    await removal_receipt(session, membership)
    detail = await MembershipStateService.detail("membership_retry_unavailable", membership, session, GUILD)
    context = detail["membership"]
    assert context["type"] == "LEGACY" and context["type_name"] is None
    assert context["id"] == membership.id and context["status"] == "REMOVED"
    assert context["discord_id"] == USER and context["removed_by"] == ACTOR
    assert context["start_date"] and context["end_date"] and context["removed_at"]


@pytest.mark.asyncio
async def test_catalog_name_equal_to_code_is_preserved_in_controlled_error_context(session, initial_player):
    membership = await period(session, initial_player[2])
    membership_type = (await session.exec(select(MembershipType).where(MembershipType.code == "regular"))).one()
    membership_type.name = membership_type.code
    session.add(membership_type)
    await session.commit()
    detail = await MembershipStateService.detail("membership_already_active", membership, session, GUILD)
    assert detail["membership"]["type"] == "regular"
    assert detail["membership"]["type_name"] == "regular"
    assert detail["membership"]["status"] == "ACTIVE"
