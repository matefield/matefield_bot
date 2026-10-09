"""Calendar errors reject edits and compensation before changing existing benefits."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlmodel import select

from src.connections.databases.db import Membership, MembershipType, Player, PlayerRole, Role
from src.modules.v1.services.memberships_service import MembershipsService


@pytest_asyncio.fixture
async def calendar_membership(session):
    player = Player(steam_id="76561198000000001")
    original_role = Role(code="ORIGINAL", name="Original", role_type="VIP")
    other_role = Role(code="OTHER", name="Other", role_type="VIP")
    session.add_all([player, original_role, other_role])
    await session.flush()
    session.add_all([
        MembershipType(code="ORIGINAL", name="Original", role_id=original_role.id),
        MembershipType(code="OTHER", name="Other", role_id=other_role.id, default_days=14),
        PlayerRole(steam_id=player.steam_id, role_id=original_role.id),
    ])
    membership = Membership(steam_id=player.steam_id, membership_type="ORIGINAL",
                            role_granted_id=original_role.id, end_time=datetime.now(timezone.utc) + timedelta(days=30))
    session.add(membership)
    await session.commit()
    return membership, original_role, other_role


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"days": 10**30}, {"add_days": 10**30}, {"days": 7, "add_days": 10**30}, {"add_days": -1}])
async def test_invalid_calendar_edit_does_not_mutate_membership_or_roles(client, session, calendar_membership, changes):
    membership, original_role, _ = calendar_membership
    original_end = membership.end_time
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={
        "membership_type": "OTHER", "is_booster": True, **changes,
    })
    assert response.status_code == 400
    assert membership.membership_type == "ORIGINAL"
    assert membership.role_granted_id == original_role.id
    assert membership.end_time == original_end
    assert membership.is_active is True and membership.is_booster is False
    assert session.is_modified(membership) is False
    assert [(row.steam_id, row.role_id) for row in (await session.exec(select(PlayerRole))).all()] == [(membership.steam_id, original_role.id)]


@pytest.mark.asyncio
async def test_type_default_overflow_is_rejected_before_changing_type(client, session, calendar_membership):
    membership, original_role, _ = calendar_membership
    other_type = (await session.exec(select(MembershipType).where(MembershipType.code == "OTHER"))).one()
    other_type.default_days = 2**31 - 1
    session.add(other_type)
    await session.commit()
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"membership_type": "OTHER"})
    assert response.status_code == 400
    assert membership.membership_type == "ORIGINAL" and membership.role_granted_id == original_role.id
    assert session.is_modified(membership) is False


@pytest.mark.asyncio
async def test_date_near_calendar_limit_rejects_extension_without_mutation(client, session, calendar_membership):
    membership = calendar_membership[0]
    membership.end_time = datetime(9999, 12, 31, tzinfo=timezone.utc)
    session.add(membership)
    await session.commit()
    original_end = membership.end_time
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"add_days": 1})
    assert response.status_code == 400
    assert membership.end_time == original_end
    assert session.is_modified(membership) is False


@pytest.mark.asyncio
async def test_compensation_prevalidates_whole_batch_before_mutating_first_member(client, session, calendar_membership, monkeypatch):
    original = calendar_membership[0]
    latest = Membership(steam_id=original.steam_id, membership_type="OTHER",
                        end_time=datetime(9999, 12, 31, tzinfo=timezone.utc))
    session.add(latest)
    await session.commit()
    original_end, latest_end = original.end_time, latest.end_time
    sync = AsyncMock()
    monkeypatch.setattr(MembershipsService, "sync_memberships_logic", sync)
    response = await client.post("/api/v1/db/memberships/compensate", json={"days": 1})
    assert response.status_code == 400
    assert original.end_time == original_end and latest.end_time == latest_end
    assert session.is_modified(original) is False and session.is_modified(latest) is False
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_compensation_preserves_permanent_memberships(client, session, calendar_membership, monkeypatch):
    original = calendar_membership[0]
    permanent = Membership(steam_id=original.steam_id, membership_type="OTHER", end_time=None)
    session.add(permanent)
    await session.commit()
    original_end = original.end_time
    sync = AsyncMock()
    monkeypatch.setattr(MembershipsService, "sync_memberships_logic", sync)
    response = await client.post("/api/v1/db/memberships/compensate", json={"days": 5})
    assert response.status_code == 200
    assert "1 memberships" in response.json()["message"]
    await session.refresh(original)
    await session.refresh(permanent)
    expected = original_end.replace(tzinfo=None) + timedelta(days=5)
    assert original.end_time.replace(tzinfo=None) == expected
    assert permanent.end_time is None
    sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_days_then_extra_days_keep_explicit_deactivation(client, session, calendar_membership):
    membership, original_role, _ = calendar_membership
    start = membership.start_time
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"days": 7, "add_days": 3, "is_active": False})
    assert response.status_code == 200
    await session.refresh(membership)
    assert membership.end_time.replace(tzinfo=None) == start.replace(tzinfo=None) + timedelta(days=10)
    assert membership.is_active is False
    assert await session.get(PlayerRole, (membership.steam_id, original_role.id)) is None


@pytest.mark.asyncio
async def test_permanent_extension_does_not_add_a_finite_expiry(client, session, calendar_membership):
    membership = calendar_membership[0]
    membership.end_time = None
    session.add(membership)
    await session.commit()
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"add_days": 10**30})
    assert response.status_code == 200
    await session.refresh(membership)
    assert membership.end_time is None and membership.is_active is True


@pytest.mark.asyncio
async def test_type_default_and_extra_days_keep_role_and_duration_behavior(client, session, calendar_membership):
    membership, original_role, other_role = calendar_membership
    start = membership.start_time
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"membership_type": "OTHER", "add_days": 3})
    assert response.status_code == 200
    await session.refresh(membership)
    assert membership.end_time.replace(tzinfo=None) == start.replace(tzinfo=None) + timedelta(days=17)
    assert membership.role_granted_id == other_role.id
    assert await session.get(PlayerRole, (membership.steam_id, original_role.id)) is None
    assert await session.get(PlayerRole, (membership.steam_id, other_role.id)) is not None


@pytest.mark.asyncio
async def test_date_edit_to_past_revokes_vip_but_keeps_special_badge(client, session, calendar_membership):
    membership, vip, _ = calendar_membership
    badge = Role(code="FOUNDER", name="Founder", role_type="SPECIAL")
    session.add(badge)
    await session.flush()
    membership.start_time = datetime.now(timezone.utc) - timedelta(days=10)
    membership.special_role_id = badge.id
    session.add_all([membership, PlayerRole(steam_id=membership.steam_id, role_id=badge.id)])
    await session.commit()
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"days": 1})
    assert response.status_code == 200
    assert membership.is_active is False
    assert await session.get(PlayerRole, (membership.steam_id, vip.id)) is None
    assert await session.get(PlayerRole, (membership.steam_id, badge.id)) is not None


@pytest.mark.asyncio
async def test_date_edit_reactivates_and_restores_membership_roles(client, session, calendar_membership):
    membership, vip, _ = calendar_membership
    assigned = await session.get(PlayerRole, (membership.steam_id, vip.id))
    await session.delete(assigned)
    membership.is_active = False
    membership.start_time = datetime.now(timezone.utc) - timedelta(days=10)
    membership.end_time = datetime.now(timezone.utc) - timedelta(days=1)
    session.add(membership)
    await session.commit()
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"days": 30})
    assert response.status_code == 200
    assert membership.is_active is True
    assert await session.get(PlayerRole, (membership.steam_id, vip.id)) is not None


@pytest.mark.asyncio
async def test_type_change_to_expired_duration_leaves_no_vip_roles(client, session, calendar_membership):
    membership, vip, other_vip = calendar_membership
    membership.start_time = datetime.now(timezone.utc) - timedelta(days=30)
    session.add(membership)
    await session.commit()
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"membership_type": "OTHER"})
    assert response.status_code == 200
    assert membership.is_active is False and membership.role_granted_id == other_vip.id
    assert await session.get(PlayerRole, (membership.steam_id, vip.id)) is None
    assert await session.get(PlayerRole, (membership.steam_id, other_vip.id)) is None


@pytest.mark.asyncio
async def test_type_change_reactivates_inactive_member_with_the_new_role(client, session, calendar_membership):
    membership, vip, other_vip = calendar_membership
    assigned = await session.get(PlayerRole, (membership.steam_id, vip.id))
    await session.delete(assigned)
    membership.is_active = False
    membership.start_time = datetime.now(timezone.utc) - timedelta(days=10)
    membership.end_time = datetime.now(timezone.utc) - timedelta(days=1)
    session.add(membership)
    await session.commit()
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"membership_type": "OTHER"})
    assert response.status_code == 200
    assert membership.is_active is True and membership.role_granted_id == other_vip.id
    assert await session.get(PlayerRole, (membership.steam_id, vip.id)) is None
    assert await session.get(PlayerRole, (membership.steam_id, other_vip.id)) is not None
