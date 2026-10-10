"""Public membership plans keep prices, defaults and Discord role links together."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import update
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipType, Player, Role
from wardogs_schemas.dtos import CreateMembershipTypeRequest, UpdateMembershipTypeRequest, MembershipWarconDelivery


@pytest.mark.asyncio
async def test_catalog_currency_units_round_trip_and_update_preserves_role(client, session):
    role = Role(code="VIP", name="VIP", discord_role_id="123456789012345678", role_type="VIP")
    session.add(role)
    await session.commit()
    response = await client.post("/api/v1/membership-types", json={
        "code": "regular", "name": "VIP NORMAL", "default_days": 30,
        "price_usd": 5, "price_ars": 7000, "role_id": role.id,
    })
    assert response.status_code == 200
    item = response.json()["membership_type"]
    assert (item["price_usd"], item["price_ars"], item["default_days"]) == (5, 7000, 30)
    stored = await session.get(MembershipType, item["id"])
    assert (stored.price_usd, stored.price_ars) == (500, 700000)

    for identifier in (str(item["id"]), "regular"):
        response = await client.get(f"/api/v1/membership-types/{identifier}")
        assert response.json()["price_ars"] == 7000
    listing = (await client.get("/api/v1/membership-types?active_only=true")).json()
    assert len(listing) == 1 and listing[0]["price_ars"] == 7000
    response = await client.put(f"/api/v1/membership-types/{item['id']}", json={"name": "VIP Normal actualizado"})
    assert response.status_code == 200
    updated = response.json()["membership_type"]
    assert (updated["price_usd"], updated["price_ars"], updated["role_id"], updated["default_days"]) == (5, 7000, role.id, 30)


@pytest.mark.asyncio
async def test_ars_null_zero_and_missing_have_distinct_meanings(client, session):
    response = await client.post("/api/v1/membership-types", json={"code": "custom", "name": "Custom"})
    item = response.json()["membership_type"]
    assert item["price_ars"] is None
    for amount in (0, 0.29, 1.005, None):
        response = await client.put(f"/api/v1/membership-types/{item['id']}", json={"price_ars": amount})
        assert response.status_code == 200
        expected = 1.01 if amount == 1.005 else amount
        assert response.json()["membership_type"]["price_ars"] == expected
        await session.refresh(await session.get(MembershipType, item["id"]))
        stored = await session.get(MembershipType, item["id"])
        assert stored.price_ars == {0: 0, 0.29: 29, 1.005: 101, None: None}[amount]


@pytest.mark.asyncio
async def test_usd_conversion_preserves_cents_and_rounds_at_currency_boundary(client, session):
    response = await client.post("/api/v1/membership-types", json={
        "code": "fractional", "name": "Fractional", "price_usd": 0.29,
    })
    item = response.json()["membership_type"]
    assert item["price_usd"] == 0.29
    assert (await session.get(MembershipType, item["id"])).price_usd == 29
    response = await client.put(f"/api/v1/membership-types/{item['id']}", json={"price_usd": 1.005})
    assert response.json()["membership_type"]["price_usd"] == 1.01


@pytest.mark.parametrize("schema", [CreateMembershipTypeRequest, UpdateMembershipTypeRequest])
@pytest.mark.parametrize("field,value", [
    ("price_usd", -1), ("price_ars", -1),
    ("price_usd", float("inf")), ("price_ars", float("inf")),
    ("price_usd", float("nan")), ("price_ars", float("nan")),
    ("default_days", -1),
])
def test_catalog_rejects_negative_days_and_invalid_prices(schema, field, value):
    with pytest.raises(ValidationError):
        schema.model_validate({"code": "test", "name": "Test", field: value})


@pytest.mark.asyncio
async def test_fresh_defaults_follow_announced_plans_and_do_not_overwrite_edits(client, session):
    plans = (await client.get("/api/v1/membership-types")).json()
    by_code = {item["code"]: item for item in plans}
    assert (by_code["VIP_COMUN"]["name"], by_code["VIP_COMUN"]["default_days"],
            by_code["VIP_COMUN"]["price_usd"], by_code["VIP_COMUN"]["price_ars"]) == ("VIP NORMAL", 30, 5, 7000)
    assert (by_code["VIP_EXPRESS"]["name"], by_code["VIP_EXPRESS"]["default_days"],
            by_code["VIP_EXPRESS"]["price_usd"], by_code["VIP_EXPRESS"]["price_ars"]) == ("VIP EXPRESS", 14, 3, 5000)
    assert by_code["VIP_PERMANENTE"]["default_days"] == 0
    assert by_code["VIP_PERMANENTE"]["price_ars"] is None
    await client.put(f"/api/v1/membership-types/{by_code['VIP_EXPRESS']['id']}", json={
        "name": "Plan editado", "default_days": 9, "price_usd": 4, "price_ars": 6000,
    })
    before = {item.id: item.model_dump() for item in (await session.exec(select(MembershipType))).all()}
    await client.get("/api/v1/membership-types")
    assert {item.id: item.model_dump() for item in (await session.exec(select(MembershipType))).all()} == before


@pytest.mark.asyncio
@pytest.mark.parametrize("code,name,days,usd,ars", [
    ("express", "VIP EXPRESS", 14, 3, 5000),
    ("regular", "VIP NORMAL", 30, 5, 7000),
])
async def test_omitted_days_reach_warcon_with_the_catalog_expiry(client, session, monkeypatch, code, name, days, usd, ars):
    role = Role(code=code.upper(), name=name, discord_role_id="123456789012345678", role_type="VIP")
    player = Player(steam_id="76561198000000001", discord_id="234567890123456789")
    session.add_all([role, player])
    await session.commit()
    response = await client.post("/api/v1/membership-types", json={
        "code": code, "name": name, "default_days": days,
        "price_usd": usd, "price_ars": ars, "role_id": role.id,
    })
    assert response.status_code == 200
    monkeypatch.setattr(WarconClient, "validate_configuration", lambda self: None)
    delivery = AsyncMock(return_value=MembershipWarconDelivery(status="SUCCESS", server_id="test-server"))
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", delivery)
    response = await client.post("/api/v1/db/players/membership", json={
        "steam_id": player.steam_id, "membership_type": code,
        "source": "DISCORD", "operation_id": f"catalog-{code}",
    })
    assert response.status_code == 200
    data = response.json()
    start = datetime.fromisoformat(data["membership"]["start_date"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(data["membership"]["end_date"].replace("Z", "+00:00"))
    assert end - start == timedelta(days=days)
    assert data["warcon"]["status"] == "SUCCESS"
    assert data["discord"]["role_ids"] == [role.discord_role_id]
    assert delivery.await_args.args == (player.steam_id, data["membership"]["id"], name, end)
    assert len((await session.exec(select(Membership))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["price_usd", "price_ars"])
@pytest.mark.parametrize("value", [21474836.48, 1e100])
async def test_oversized_currency_is_rejected_before_create_or_update(client, session, field, value):
    created = await client.post("/api/v1/membership-types", json={"code": "regular", "name": "VIP Normal"})
    item_id = created.json()["membership_type"]["id"]
    assert (await client.post("/api/v1/membership-types", json={"code": "oversized", "name": "Oversized", field: value})).status_code == 422
    assert (await client.put(f"/api/v1/membership-types/{item_id}", json={field: value})).status_code == 422
    assert len((await session.exec(select(MembershipType))).all()) == 1
    assert (await session.get(MembershipType, item_id)).price_usd == 0
    assert (await session.get(MembershipType, item_id)).price_ars is None


@pytest.mark.asyncio
async def test_role_creation_and_type_validation_are_one_transaction(client, session):
    response = await client.post("/api/v1/membership-types", json={
        "code": "invalid", "name": "Invalid", "discord_role_id": "123456789012345678", "billing_type": "INVALID",
    })
    assert response.status_code == 400
    # The real dependency closes and rolls back failed requests. The client
    # fixture shares a session, so perform that same rollback explicitly here.
    await session.rollback()
    assert (await session.exec(select(Role))).all() == []
    assert (await session.exec(select(MembershipType))).all() == []


@pytest.mark.asyncio
async def test_invalid_type_update_does_not_commit_a_new_role_or_server_change(client, session):
    from src.connections.databases.db import RconServer

    original = MembershipType(code="regular", name="VIP Normal")
    server = RconServer(name="Test", ip="rcon.test", port=7776, password="test-only")
    session.add_all([original, server])
    await session.commit()
    original_id = original.id
    response = await client.put(f"/api/v1/membership-types/{original_id}", json={
        "server_id": server.id, "discord_role_id": "123456789012345678", "billing_type": "INVALID",
    })
    assert response.status_code == 400
    await session.rollback()
    saved = await session.get(MembershipType, original_id)
    assert saved.role_id is None and saved.server_id is None
    assert (await session.exec(select(Role))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("code", "   "), ("name", "   "), ("code", "x" * 101), ("name", "x" * 256)])
async def test_catalog_rejects_empty_or_unsupported_discord_labels(client, session, field, value):
    payload = {"code": "regular", "name": "VIP Normal", field: value}
    assert (await client.post("/api/v1/membership-types", json=payload)).status_code == 422
    assert (await session.exec(select(MembershipType))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["   ", "x" * 256])
async def test_catalog_update_rejects_invalid_name_and_preserves_existing_type(client, session, value):
    created = (await client.post("/api/v1/membership-types", json={"code": "regular", "name": "VIP Normal"})).json()
    item_id = created["membership_type"]["id"]
    assert (await client.put(f"/api/v1/membership-types/{item_id}", json={"name": value})).status_code == 422
    assert (await session.get(MembershipType, item_id)).name == "VIP Normal"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("default_days", 2**31), ("max_quota", 2**31), ("max_quota", -1)])
async def test_catalog_rejects_counts_outside_database_range(client, session, field, value):
    created = (await client.post("/api/v1/membership-types", json={"code": "regular", "name": "VIP Normal"})).json()
    item_id = created["membership_type"]["id"]
    assert (await client.post("/api/v1/membership-types", json={"code": "invalid", "name": "Invalid", field: value})).status_code == 422
    assert (await client.put(f"/api/v1/membership-types/{item_id}", json={field: value})).status_code == 422
    assert len((await session.exec(select(MembershipType))).all()) == 1


@pytest.mark.asyncio
async def test_nullable_upstream_usd_price_is_presented_as_zero_without_overwriting_storage(client, session):
    plan = MembershipType(code="FREE", name="Free membership")
    session.add(plan)
    await session.commit()
    # INSERT applies the ORM default of zero. Imported upstream rows can still
    # contain NULL, so persist that state explicitly before exercising the API.
    await session.exec(update(MembershipType).where(MembershipType.id == plan.id).values(price_usd=None))
    await session.commit()
    await session.refresh(plan)
    assert plan.price_usd is None
    listing = await client.get("/api/v1/membership-types")
    assert listing.status_code == 200 and listing.json()[0]["price_usd"] == 0
    item = await client.get(f"/api/v1/membership-types/{plan.id}")
    assert item.status_code == 200 and item.json()["price_usd"] == 0
    renamed = await client.put(f"/api/v1/membership-types/{plan.id}", json={"name": "Free renamed"})
    assert renamed.status_code == 200 and renamed.json()["membership_type"]["price_usd"] == 0
    await session.refresh(plan)
    assert plan.price_usd is None
