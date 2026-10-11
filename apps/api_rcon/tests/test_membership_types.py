import pytest
from sqlmodel import select
from src.connections.databases.db import Membership, MembershipType, Player


@pytest.mark.asyncio
async def test_membership_type_defaults_and_quota_enforcement(client, session):
    # 1. Setup player and package with quota = 1
    session.add(Player(steam_id="STEAM_P1", in_game_name="Player1"))
    session.add(Player(steam_id="STEAM_P2", in_game_name="Player2"))
    session.add(MembershipType(
        code="VIP_LIMITED",
        name="VIP Limitado",
        price_usd=25.0,
        billing_type="ONE_TIME",
        default_days=45,
        max_quota=1,
        is_active=True
    ))
    await session.commit()

    # 2. Add membership without days: should inherit default_days=45
    resp = await client.post("/api/v1/db/players/membership", json={
        "steam_id": "STEAM_P1",
        "membership_type": "VIP_LIMITED"
    })
    assert resp.status_code == 200

    # Verify duration
    m = (await session.exec(select(Membership).where(Membership.steam_id == "STEAM_P1"))).first()
    assert m is not None
    assert m.is_active is True
    assert m.end_time is not None
    delta = m.end_time - m.start_time
    assert delta.days in (44, 45) # depending on second precision

    # 3. Try to add for second player: should fail because quota is 1
    resp = await client.post("/api/v1/db/players/membership", json={
        "steam_id": "STEAM_P2",
        "membership_type": "VIP_LIMITED"
    })
    assert resp.status_code == 400
    assert "No hay cupos disponibles" in resp.json()["detail"]


