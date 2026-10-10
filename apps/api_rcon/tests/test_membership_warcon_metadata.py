"""Warcon metadata comes from the API's membership catalog, including replays."""
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipType, Player, Role
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import MembershipWarconDelivery


@pytest.fixture
def warcon_delivery(monkeypatch):
    settings = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    for key, value in {
        "WARCON_URL": "http://warcon.test", "WARCON_ORG_ID": "test-org",
        "WARCON_SERVER_ID": "test-server", "WARCON_API_TOKEN": "wck_test_only",
    }.items():
        monkeypatch.setattr(settings, key, value)
    delivery = AsyncMock(return_value=MembershipWarconDelivery(
        status="SUCCESS", server_id="test-server", entry_id="test-entry",
    ))
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", delivery)
    return delivery


@pytest_asyncio.fixture
async def catalog_type(session):
    role = Role(code="CUSTOM_PLAN", name="Rol de colaboradores", role_type="VIP",
                discord_role_id="123456789012345678")
    player = Player(steam_id="76561198000000001", discord_id="234567890123456789")
    session.add_all([role, player])
    await session.flush()
    membership_type = MembershipType(code="Custom_Plan", name="VIP Colaboradores — 30 días",
                                     default_days=30, role_id=role.id)
    session.add(membership_type)
    await session.commit()
    return membership_type


def payload(membership_type="custom_plan"):
    return {
        "steam_id": "76561198000000001", "membership_type": membership_type,
        "source": "DISCORD", "operation_id": "345678901234567890",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["CUSTOM_PLAN", "custom_plan", "CuStOm_PlAn"])
async def test_delivery_uses_custom_catalog_name_with_case_insensitive_code(
    client, session, catalog_type, warcon_delivery, code,
):
    response = await client.post("/api/v1/db/players/membership", json=payload(code))

    assert response.status_code == 200
    assert response.json()["membership"]["type"] == "Custom_Plan"
    saved = (await session.exec(select(Membership))).one()
    assert warcon_delivery.await_args.args[:3] == (
        saved.steam_id, saved.id, "VIP Colaboradores — 30 días",
    )
    assert (saved.end_time - saved.start_time).days == 30


@pytest.mark.asyncio
async def test_replay_uses_current_name_of_disabled_type_without_extending_membership(
    client, session, catalog_type, warcon_delivery,
):
    first = await client.post("/api/v1/db/players/membership", json=payload())
    assert first.status_code == 200
    catalog_type.name = "VIP Comunidad"
    catalog_type.is_active = False
    session.add(catalog_type)
    await session.commit()

    replay = await client.post("/api/v1/db/players/membership", json=payload())

    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["membership"] == first.json()["membership"]
    assert len((await session.exec(select(Membership))).all()) == 1
    assert warcon_delivery.await_count == 2
    assert warcon_delivery.await_args_list[0].args[2] == "VIP Colaboradores — 30 días"
    assert warcon_delivery.await_args_list[1].args[2] == "VIP Comunidad"
    assert warcon_delivery.await_args_list[1].args[3] == warcon_delivery.await_args_list[0].args[3]


@pytest.mark.asyncio
async def test_replay_rejects_missing_catalog_type_before_contacting_warcon(
    client, session, catalog_type, warcon_delivery,
):
    first = await client.post("/api/v1/db/players/membership", json=payload())
    assert first.status_code == 200
    await session.delete(catalog_type)
    await session.commit()

    replay = await client.post("/api/v1/db/players/membership", json=payload())

    assert replay.status_code == 409
    assert replay.json()["detail"] == "El tipo de esta membresía ya no está registrado en nuestro sistema."
    assert warcon_delivery.await_count == 1
    saved = (await session.exec(select(Membership))).one()
    assert saved.id == first.json()["membership"]["id"]
    assert saved.is_active is True
