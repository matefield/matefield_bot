"""Initial VIP grants use the same durable role lifecycle as scheduled renewals."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipRenewalDelivery, PlayerRole, RoleDiscordBinding
from src.modules.v1.services.membership_deliveries_service import MembershipDeliveriesService
from wardogs_schemas.dtos import MembershipWarconDelivery
from test_membership_renewals import (
    ACTOR, BADGE, GUILD, NEW_ROLE, OLD_ROLE, OTHER_GUILD, STEAM, USER,
    deliveries_mock, freeze, renewal_player, utc,
)

ADD_URL = "/api/v1/db/players/membership"
QUEUE_URL = "/api/v1/discord/membership-deliveries"


@pytest_asyncio.fixture
async def initial_player(session, renewal_player):
    player, previous, old_role, new_role, badge = renewal_player
    await session.delete(previous)
    await session.delete(await session.get(PlayerRole, (STEAM, old_role.id)))
    await session.commit()
    return player, old_role, new_role, badge


def payload(**values):
    return dict(steam_id=STEAM, membership_type="regular", source="DISCORD", guild_id=GUILD,
                actor_id=ACTOR, operation_id="add-initial", **values)


async def queued(client):
    response = await client.get(QUEUE_URL, params={"guild_id": GUILD})
    assert response.status_code == 200
    return response.json()["deliveries"]


@pytest.mark.asyncio
@pytest.mark.parametrize("days,phases", [(30, ["START", "END"]), (0, ["START"])])
async def test_initial_receipts_are_committed_before_warcon(client, session, initial_player, deliveries_mock, monkeypatch, days, phases):
    async def inspect_saved(*_args):
        membership = (await session.exec(select(Membership))).one()
        receipts = (await session.exec(select(MembershipRenewalDelivery).order_by(MembershipRenewalDelivery.id))).all()
        assert [receipt.phase for receipt in receipts] == phases
        assert all(receipt.membership_id == membership.id and receipt.previous_membership_id is None for receipt in receipts)
        assert receipts[0].activated and not receipts[0].completed
        assert all(receipt.actor_id == ACTOR for receipt in receipts)
        return MembershipWarconDelivery(status="SUCCESS", server_id="game", entry_id="entry")
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", inspect_saved)
    response = await client.post(ADD_URL, json=payload(days=days))
    assert response.status_code == 200
    result = response.json()
    assert result["delivery"]["previous_membership_id"] is None
    assert result["delivery"]["role_ids_to_add"] == [NEW_ROLE]
    assert result["delivery"]["role_ids_to_remove"] == []
    assert len(await queued(client)) == 1


@pytest.mark.asyncio
async def test_warcon_and_discord_recover_independently_without_new_period(client, session, test_engine, initial_player, deliveries_mock):
    upsert, _ = deliveries_mock
    upsert.return_value = MembershipWarconDelivery(status="FAILED", server_id="game", error="offline")
    created = (await client.post(ADD_URL, json=payload())).json()
    assert created["warcon"]["status"] == "FAILED"
    receipt = (await queued(client))[0]
    assert receipt["role_ids_to_add"] == [NEW_ROLE]
    # Discord can succeed while Warcon is still unavailable. Its ACK never clears
    # the independent persisted Warcon failure, even after a process restart.
    completed = await client.post(f"{QUEUE_URL}/{receipt['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    assert completed.status_code == 200
    assert await queued(client) == []
    upsert.return_value = MembershipWarconDelivery(status="SUCCESS", server_id="game", entry_id="entry")
    await MembershipDeliveriesService.retry_pending(test_engine)
    membership = (await session.exec(select(Membership))).one()
    await session.refresh(membership)
    assert membership.id == created["membership"]["id"] and membership.rcon_sync_status == "SUCCESS"
    assert utc(membership.end_time) == datetime.fromisoformat(created["membership"]["end_date"])
    assert upsert.await_count == 2
    assert len((await session.exec(select(Membership))).all()) == 1


@pytest.mark.asyncio
async def test_retry_repairs_saved_grant_and_lost_role_ack(client, session, initial_player, deliveries_mock):
    created = (await client.post(ADD_URL, json=payload())).json()
    first = await queued(client)
    assert await queued(client) == first  # Failed Discord delivery or ACK is retried.
    repaired = await client.post(f"/api/v1/db/memberships/{created['membership']['id']}/retry", json={"guild_id": GUILD, "actor_id": ACTOR})
    assert repaired.status_code == 200
    assert repaired.json()["membership"] == created["membership"]
    assert repaired.json()["delivery"] == created["delivery"]
    assert repaired.json()["replayed"] is True
    completed = await client.post(f"{QUEUE_URL}/{first[0]['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    assert completed.status_code == 200 and await queued(client) == []
    assert len((await session.exec(select(Membership))).all()) == 1


@pytest.mark.asyncio
async def test_initial_expiration_deactivates_and_delivers_without_warcon_io(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    membership = (await session.exec(select(Membership))).one()
    freeze(monkeypatch, utc(membership.end_time) + timedelta(seconds=1))
    # The API expires its own entitlement without contacting Warcon. Warcon owns
    # expiresAt and its game poller, so an outage cannot keep a Discord role alive.
    expired = await queued(client)
    assert len(expired) == 1
    assert expired[0]["role_ids_to_add"] == [] and expired[0]["role_ids_to_remove"] == [NEW_ROLE]
    await session.refresh(membership)
    assert membership.is_active is False
    assert await session.get(PlayerRole, (STEAM, initial_player[2].id)) is None
    assert await session.get(PlayerRole, (STEAM, initial_player[3].id)) is not None
    assert deliveries_mock[0].await_count == 1
    deliveries_mock[1].assert_not_awaited()


@pytest.mark.asyncio
async def test_offline_bot_until_expiration_never_regrants_initial_role(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    membership = (await session.exec(select(Membership))).one()
    freeze(monkeypatch, utc(membership.end_time) + timedelta(days=1))
    expired = await queued(client)
    assert len(expired) == 2
    assert all(delivery["role_ids_to_add"] == [] and delivery["role_ids_to_remove"] == [NEW_ROLE] for delivery in expired)
    repaired = await client.post(f"/api/v1/db/memberships/{membership.id}/retry", json={"guild_id": GUILD, "actor_id": ACTOR})
    assert repaired.status_code == 409
    assert deliveries_mock[0].await_count == 1
    assert datetime.fromisoformat(created["membership"]["end_date"]) == utc(membership.end_time)


@pytest.mark.asyncio
async def test_expired_failed_warcon_is_not_recreated_by_maintenance(client, session, test_engine, initial_player, deliveries_mock, monkeypatch):
    deliveries_mock[0].return_value = MembershipWarconDelivery(status="FAILED", server_id="game", error="offline")
    await client.post(ADD_URL, json=payload())
    membership = (await session.exec(select(Membership))).one()
    freeze(monkeypatch, utc(membership.end_time) + timedelta(days=1))
    await MembershipDeliveriesService.retry_pending(test_engine)
    assert deliveries_mock[0].await_count == 1
    assert len(await queued(client)) == 2


@pytest.mark.asyncio
async def test_retry_and_ack_are_bound_to_original_guild_and_user(client, session, initial_player, deliveries_mock):
    created = (await client.post(ADD_URL, json=payload())).json()
    retry_url = f"/api/v1/db/memberships/{created['membership']['id']}/retry"
    denied = await client.post(retry_url, json={"guild_id": OTHER_GUILD, "actor_id": ACTOR})
    assert denied.status_code == 409 and denied.json()["detail"]["code"] == "membership_retry_other_guild"
    receipt_id = created["delivery"]["id"]
    wrong_user = await client.post(f"{QUEUE_URL}/{receipt_id}/complete", json={"guild_id": GUILD, "user_id": ACTOR})
    assert wrong_user.status_code == 409
    player = initial_player[0]
    player.discord_id = ACTOR
    session.add(player)
    await session.commit()
    changed_account = await client.post(retry_url, json={"guild_id": GUILD, "actor_id": ACTOR})
    assert changed_account.status_code == 409
    assert await queued(client) == []
    assert deliveries_mock[0].await_count == 1


@pytest.mark.asyncio
async def test_pending_initial_grant_can_be_cancelled_without_regrant(client, session, initial_player, deliveries_mock):
    await client.post(ADD_URL, json=payload())
    response = await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={"guild_id": GUILD, "actor_id": ACTOR, "operation_id": "cancel-initial"})
    assert response.status_code == 200
    receipts = (await session.exec(select(MembershipRenewalDelivery))).all()
    assert all(receipt.cancelled for receipt in receipts)
    assert await queued(client) == []
    deliveries_mock[1].assert_awaited_once()


@pytest.mark.asyncio
async def test_actor_metadata_does_not_change_original_add_idempotency(client, session, initial_player, deliveries_mock):
    original = payload()
    del original["actor_id"]
    created = (await client.post(ADD_URL, json=original)).json()
    replay = await client.post(ADD_URL, json=payload())
    assert replay.status_code == 200
    assert replay.json()["membership"] == created["membership"]
    assert len((await session.exec(select(Membership))).all()) == 1


@pytest.mark.asyncio
async def test_late_start_uses_expiration_vip_snapshot_not_special_role_order(client, session, initial_player, deliveries_mock, monkeypatch):
    # Backfilled START snapshots need not have their primary VIP first. The END
    # snapshot identifies the revocable role without guessing from array order.
    created = (await client.post(ADD_URL, json=payload())).json()
    start = await session.get(MembershipRenewalDelivery, created["delivery"]["id"])
    start.role_ids_to_add_json = f'["{BADGE}", "{NEW_ROLE}"]'
    binding = (await session.exec(select(RoleDiscordBinding).where(RoleDiscordBinding.discord_role_id == BADGE))).one()
    binding.discord_role_id = "444444444444444447"
    session.add_all([start, binding])
    await session.commit()
    membership = (await session.exec(select(Membership))).one()
    freeze(monkeypatch, utc(membership.end_time) + timedelta(seconds=1))
    deliveries = await queued(client)
    assert all(delivery["role_ids_to_remove"] == [NEW_ROLE] for delivery in deliveries)
    assert all(BADGE not in delivery["role_ids_to_remove"] for delivery in deliveries)


@pytest.mark.asyncio
async def test_individual_delivery_refresh_discards_cancelled_or_completed_batch_item(client, session, initial_player, deliveries_mock):
    created = (await client.post(ADD_URL, json=payload())).json()
    stale = (await queued(client))[0]
    refreshed = await client.get(f"{QUEUE_URL}/{stale['id']}", params={"guild_id": GUILD})
    assert refreshed.status_code == 200 and refreshed.json() == stale
    other_guild = await client.get(f"{QUEUE_URL}/{stale['id']}", params={"guild_id": OTHER_GUILD})
    assert other_guild.status_code == 404
    await client.post(f"/api/v1/db/players/{STEAM}/membership/remove", json={"guild_id": GUILD, "actor_id": ACTOR, "operation_id": "cancel-batched"})
    cancelled = await client.get(f"{QUEUE_URL}/{stale['id']}", params={"guild_id": GUILD})
    assert cancelled.status_code == 404
    assert created["delivery"]["id"] == stale["id"]


@pytest.mark.asyncio
async def test_individual_delivery_refresh_after_expiry_never_grants_stale_role(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    membership = (await session.exec(select(Membership))).one()
    freeze(monkeypatch, utc(membership.end_time) + timedelta(seconds=1))
    refreshed = await client.get(f"{QUEUE_URL}/{created['delivery']['id']}", params={"guild_id": GUILD})
    assert refreshed.status_code == 200
    assert refreshed.json()["role_ids_to_add"] == [] and refreshed.json()["role_ids_to_remove"] == [NEW_ROLE]


@pytest.mark.asyncio
async def test_compensation_reschedules_initial_expiry_and_retries_warcon(client, session, test_engine, initial_player, deliveries_mock):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    membership = (await session.exec(select(Membership))).one()
    original_end = utc(membership.end_time)
    compensation = await client.post("/api/v1/db/memberships/compensate", json={"days": 2})
    assert compensation.status_code == 200
    await session.refresh(membership)
    expiration = (await session.exec(select(MembershipRenewalDelivery).where(MembershipRenewalDelivery.phase == "END"))).one()
    assert utc(membership.end_time) == original_end + timedelta(days=2)
    assert utc(expiration.available_at) == utc(membership.end_time)
    assert membership.rcon_sync_status == "PENDING"
    await MembershipDeliveriesService.retry_pending(test_engine)
    deliveries_mock[0].assert_awaited_with(STEAM, membership.id, "VIP Normal", utc(membership.end_time))


@pytest.mark.asyncio
async def test_initial_expiry_edit_handles_permanent_and_finite_without_duplicates(client, session, initial_player, deliveries_mock):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    membership_id = created["membership"]["id"]
    permanent = await client.put(f"/api/v1/db/memberships/{membership_id}", json={"days": 0})
    assert permanent.status_code == 200
    expiration = (await session.exec(select(MembershipRenewalDelivery).where(MembershipRenewalDelivery.phase == "END"))).one()
    assert expiration.cancelled is True
    finite = await client.put(f"/api/v1/db/memberships/{membership_id}", json={"days": 14})
    assert finite.status_code == 200
    await session.refresh(expiration)
    membership = await session.get(Membership, membership_id)
    assert expiration.cancelled is False and utc(expiration.available_at) == utc(membership.end_time)
    assert len((await session.exec(select(MembershipRenewalDelivery))).all()) == 2


@pytest.mark.asyncio
async def test_individual_old_end_activates_entire_renewal_chain_before_revoking_roles(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    renewed = await client.post("/api/v1/db/players/membership/renew", json={"steam_id": STEAM, "membership_type": "regular", "operation_id": "renew-same-vip", "guild_id": GUILD, "actor_id": ACTOR})
    assert renewed.status_code == 200
    current = await session.get(Membership, created["membership"]["id"])
    expiration = (await session.exec(select(MembershipRenewalDelivery).where(MembershipRenewalDelivery.membership_id == current.id, MembershipRenewalDelivery.phase == "END"))).one()
    freeze(monkeypatch, utc(current.end_time) + timedelta(seconds=1))
    result = await client.get(f"{QUEUE_URL}/{expiration.id}", params={"guild_id": GUILD})
    assert result.status_code == 200
    assert result.json()["role_ids_to_remove"] == []
    future = await session.get(Membership, renewed.json()["membership"]["id"])
    await session.refresh(future)
    assert future.is_active and not future.is_scheduled
    assert await session.get(PlayerRole, (STEAM, initial_player[2].id)) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,code", [
    ({"membership_type": "express"}, "membership_type_change_requires_renewal"),
    ({"server_id": 23}, "membership_scope_change_unsupported"),
    ({"is_active": False}, "membership_deactivation_requires_removal"),
])
async def test_legacy_edits_cannot_bypass_managed_role_and_warcon_lifecycle(client, session, initial_player, deliveries_mock, changes, code):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    membership = (await session.exec(select(Membership))).one()
    original_end = utc(membership.end_time)
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json=changes)
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    await session.refresh(membership)
    assert membership.is_active and membership.membership_type == "regular" and membership.server_id is None
    assert utc(membership.end_time) == original_end and membership.rcon_sync_status == "SUCCESS"
    assert await session.get(PlayerRole, (STEAM, initial_player[2].id)) is not None


@pytest.mark.asyncio
async def test_expired_managed_membership_cannot_be_reactivated_by_legacy_edit(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    membership = (await session.exec(select(Membership))).one()
    freeze(monkeypatch, utc(membership.end_time) + timedelta(seconds=1))
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"add_days": 7, "is_active": True})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_expiration_finalized"
    assert deliveries_mock[0].await_count == 1


@pytest.mark.asyncio
async def test_shortening_initial_period_to_past_requires_explicit_removal(client, session, initial_player, deliveries_mock, monkeypatch):
    created = (await client.post(ADD_URL, json=payload())).json()
    await client.post(f"{QUEUE_URL}/{created['delivery']['id']}/complete", json={"guild_id": GUILD, "user_id": USER})
    membership = (await session.exec(select(Membership))).one()
    original_end = utc(membership.end_time)
    freeze(monkeypatch, utc(membership.start_time) + timedelta(days=7))
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"days": 2})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "membership_deactivation_requires_removal"
    await session.refresh(membership)
    assert membership.is_active and utc(membership.end_time) == original_end
    assert await session.get(PlayerRole, (STEAM, initial_player[2].id)) is not None
