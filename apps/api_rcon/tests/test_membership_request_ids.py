"""Membership request IDs must fit their SQL columns before queries or writes."""
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipType, Player, Role
from wardogs_schemas.dtos import AddMembershipRequest, CreateMembershipTypeRequest, UpdateMembershipTypeRequest, EditMembershipRequest, QuotaUpdateRequest


@pytest_asyncio.fixture
async def request_catalog(session):
    player = Player(steam_id="76561198000000001")
    role = Role(code="REGULAR", name="VIP", role_type="VIP")
    session.add_all([player, role])
    await session.flush()
    m_type = MembershipType(code="regular", name="VIP Normal", role_id=role.id)
    session.add(m_type)
    await session.commit()
    return player, role, m_type


@pytest.mark.parametrize("schema,field", [
    (AddMembershipRequest, "special_role_id"), (AddMembershipRequest, "role_granted_id"),
    (CreateMembershipTypeRequest, "role_id"), (CreateMembershipTypeRequest, "server_id"),
    (UpdateMembershipTypeRequest, "role_id"), (UpdateMembershipTypeRequest, "server_id"),
    (EditMembershipRequest, "server_id"),
])
@pytest.mark.parametrize("value", [0, 2**31])
def test_domain_id_bounds_are_validated_in_shared_requests(schema, field, value):
    with pytest.raises(ValidationError):
        schema.model_validate({"steam_id": "76561198000000001", "membership_type": "regular",
                               "code": "regular", "name": "VIP Normal", field: value})


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["special_role_id", "role_granted_id"])
async def test_membership_request_rejects_oversized_role_before_write(client, session, request_catalog, field):
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": request_catalog[0].steam_id, "membership_type": "regular", field: 10**30,
    })
    assert response.status_code == 422
    assert (await session.exec(select(Membership))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["role_id", "server_id"])
async def test_type_requests_reject_oversized_id_before_lookup(client, session, request_catalog, field):
    body = {"code": "other", "name": "Other", field: 10**30}
    assert (await client.post("/api/v1/membership-types", json=body)).status_code == 422
    assert (await client.put(f"/api/v1/membership-types/{request_catalog[2].id}", json=body)).status_code == 422
    assert len((await session.exec(select(MembershipType))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("max_quota", [-1, 2**31, 10**30])
async def test_quota_update_rejects_counts_outside_storage_range(client, session, request_catalog, max_quota):
    response = await client.put("/api/v1/db/quotas/regular", json={"max_quota": max_quota})
    assert response.status_code == 422
    assert request_catalog[2].max_quota is None
    with pytest.raises(ValidationError):
        QuotaUpdateRequest(max_quota=max_quota)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"special_role_id": 99999}, {"role_granted_id": 99999}, {"server_id": 99999}])
async def test_legacy_missing_foreign_key_does_not_create_membership(client, session, request_catalog, changes):
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": request_catalog[0].steam_id, "membership_type": "regular", **changes,
    })
    assert response.status_code == 404
    assert (await session.exec(select(Membership))).all() == []


@pytest.mark.asyncio
async def test_legacy_oversized_server_id_is_rejected_before_lookup(client, session, request_catalog):
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": request_catalog[0].steam_id, "membership_type": "regular", "server_id": 10**30,
    })
    assert response.status_code == 400
    assert (await session.exec(select(Membership))).all() == []


@pytest.mark.asyncio
async def test_discord_server_rejection_preserves_its_existing_message(client, session, request_catalog, monkeypatch):
    monkeypatch.setattr(WarconClient, "validate_configuration", lambda self: None)
    delivery = AsyncMock()
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", delivery)
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": request_catalog[0].steam_id, "membership_type": "regular",
        "source": "DISCORD", "operation_id": "large-server", "server_id": 10**30,
    })
    assert response.status_code == 400
    assert "todavía no admiten un servidor específico" in response.json()["detail"]
    assert (await session.exec(select(Membership))).all() == []
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_missing_server_keeps_membership_intact(client, session, request_catalog):
    membership = Membership(steam_id=request_catalog[0].steam_id, membership_type="regular")
    session.add(membership)
    await session.commit()
    response = await client.put(f"/api/v1/db/memberships/{membership.id}", json={"server_id": 99999, "is_booster": True})
    assert response.status_code == 404
    assert membership.server_id is None and membership.is_booster is False
    assert session.is_modified(membership) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["db/memberships", "membership-types"])
@pytest.mark.parametrize("identifier", [0, 2**31])
async def test_edit_delete_path_ids_are_bounded_before_database_lookup(client, request_catalog, path, identifier):
    target = f"/api/v1/{path}/{identifier}"
    assert (await client.put(target, json={})).status_code == 422
    assert (await client.delete(target)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["²", "9" * 5000, "2147483648"])
async def test_type_lookup_handles_unicode_and_oversized_numeric_identifiers(client, request_catalog, identifier):
    assert (await client.get(f"/api/v1/membership-types/{identifier}")).status_code == 404


@pytest.mark.asyncio
async def test_out_of_range_numeric_type_code_is_still_readable_as_code(client, session):
    m_type = MembershipType(code="2147483648", name="Numeric code")
    session.add(m_type)
    await session.commit()
    response = await client.get("/api/v1/membership-types/2147483648")
    assert response.status_code == 200
    assert response.json()["code"] == m_type.code


@pytest.mark.asyncio
async def test_legacy_unicode_special_role_is_a_name_instead_of_integer(client, session, request_catalog):
    special = Role(code="BADGE", name="²", role_type="SPECIAL")
    session.add(special)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": request_catalog[0].steam_id, "membership_type": "regular", "special_role": "²",
    })
    assert response.status_code == 200
    assert (await session.exec(select(Membership))).one().special_role_id == special.id


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["page", "limit"])
@pytest.mark.parametrize("value", [-1, 0, 2**31, 10**30])
async def test_list_rejects_pagination_outside_sql_range(client, request_catalog, field, value):
    assert (await client.get(f"/api/v1/db/memberships?{field}={value}")).status_code == 422


@pytest.mark.asyncio
async def test_list_accepts_existing_large_page_sizes_with_safe_offset(client, request_catalog):
    response = await client.get(f"/api/v1/db/memberships?page={2**31-1}&limit={2**31-1}")
    assert response.status_code == 200
    assert response.json()["memberships"] == []
