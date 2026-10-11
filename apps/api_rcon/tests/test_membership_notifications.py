"""Upstream expiration notification endpoints survive the guild-delivery merge."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from src.connections.databases.db import Membership, Player
from src.main import app
from src.security.guard import verify_api_key_guard

STEAM = "76561198000000001"
DISCORD = "666666666666666666"
EXPIRING_URL = "/api/v1/db/memberships/expiring"


def mark_url(membership_id, kind="3d"):
    return f"/api/v1/db/memberships/{membership_id}/mark_notified?notification_type={kind}"


@pytest.mark.asyncio
async def test_expiring_notifications_use_priority_windows_with_persisted_naive_dates(client, session):
    now = datetime.now(timezone.utc)
    player = Player(steam_id=STEAM, discord_id=DISCORD)
    session.add(player)
    await session.flush()
    rows = [
        Membership(steam_id=STEAM, membership_type="regular", end_time=now + timedelta(days=2)),
        Membership(steam_id=STEAM, membership_type="express", end_time=now + timedelta(hours=12)),
        Membership(steam_id=STEAM, membership_type="regular", end_time=now + timedelta(days=5)),
        Membership(steam_id=STEAM, membership_type="regular", end_time=None),
        Membership(steam_id=STEAM, membership_type="regular", is_active=False, end_time=now + timedelta(hours=12)),
        Membership(steam_id=STEAM, membership_type="regular", notified_3d=True, notified_24h=True,
                   end_time=now + timedelta(hours=12)),
    ]
    session.add_all(rows)
    await session.commit()
    ids = [row.id for row in rows]
    # Match a fresh request: persisted SQLite datetime values do not retain tzinfo.
    session.expire_all()

    response = await client.get(EXPIRING_URL)
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["expiring_3d"]] == [ids[0]]
    assert [item["id"] for item in payload["expiring_24h"]] == [ids[1]]
    assert payload["expiring_3d"][0]["discord_id"] == DISCORD
    assert payload["expiring_24h"][0]["type"] == "express"

    for kind in ["3d", "24h"]:
        assert (await client.post(mark_url(ids[1], kind))).json() == {"ok": True}
    repeated = (await client.get(EXPIRING_URL)).json()
    assert repeated["expiring_24h"] == []
    assert [item["id"] for item in repeated["expiring_3d"]] == [ids[0]]


@pytest.mark.asyncio
async def test_expiring_notifications_skip_players_without_discord_link(client, session):
    session.add(Player(steam_id=STEAM))
    await session.flush()
    session.add(Membership(steam_id=STEAM, membership_type="regular",
                           end_time=datetime.now(timezone.utc) + timedelta(days=2)))
    await session.commit()
    assert (await client.get(EXPIRING_URL)).json() == {"expiring_3d": [], "expiring_24h": []}


@pytest.mark.asyncio
async def test_mark_notified_is_idempotent_and_does_not_change_membership_entitlement(client, session):
    session.add(Player(steam_id=STEAM, discord_id=DISCORD))
    await session.flush()
    membership = Membership(steam_id=STEAM, membership_type="regular",
                            end_time=datetime.now(timezone.utc) + timedelta(days=2))
    session.add(membership)
    await session.commit()
    original = membership.model_dump(exclude={"notified_3d", "notified_24h"})
    first = await client.post(mark_url(membership.id))
    repeated = await client.post(mark_url(membership.id))
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json() == {"ok": True}
    stored = (await session.exec(select(Membership))).one()
    assert stored.notified_3d is True and stored.notified_24h is False
    assert stored.model_dump(exclude={"notified_3d", "notified_24h"}) == original


@pytest.mark.asyncio
async def test_mark_notified_preserves_upstream_not_found_and_invalid_kind_responses(client):
    assert (await client.post(mark_url(1, "unknown"))).status_code == 400
    assert (await client.post(mark_url(1))).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("membership_id", [0, -1, 2 ** 31, 10 ** 30])
async def test_mark_notified_rejects_out_of_range_database_ids(client, membership_id):
    assert (await client.post(mark_url(membership_id))).status_code == 422


@pytest.mark.asyncio
async def test_api_key_guard_applies_to_notification_endpoints(client):
    saved_guard = app.dependency_overrides.pop(verify_api_key_guard)
    try:
        assert (await client.get(EXPIRING_URL)).status_code == 403
        assert (await client.post(mark_url(1))).status_code == 403
    finally:
        app.dependency_overrides[verify_api_key_guard] = saved_guard
