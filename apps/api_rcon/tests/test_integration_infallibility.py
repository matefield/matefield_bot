import asyncio

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.apis.rcon import RCONClient
from src.connections.databases.db import Membership
from src.modules.v1.services.server_service import ServerService
from wardogs_schemas import v1 as schemas


@pytest.mark.asyncio
async def test_concurrent_vip_and_ban_sync_atomicity(session: AsyncSession):
    """
    Infallibility Test:
    Simulate real concurrency between sync_reserved_slots (136 VIPs) and sync_banned_slots (50 bans).
    With _config_lock, neither process overwrites the other, and the final INI has BOTH sets intact.
    """
    base_ini = "[/Script/WDGame.WDGameSession]\nServerName=Matefield\n"
    rcon = RCONClient("http://fake:7776", "secret")

    # In-memory server simulation
    server_state = {
        "text": base_ini,
        "revision": "rev_0"
    }
    rev_counter = 0

    async def fake_get_config():
        await asyncio.sleep(0.01) # simulate network latency
        return schemas.Config1(text=server_state["text"], revision=server_state["revision"])

    async def fake_update_config(revision: str, new_text: str):
        nonlocal rev_counter
        await asyncio.sleep(0.01) # simulate server apply latency
        rev_counter += 1
        server_state["text"] = new_text
        server_state["revision"] = f"rev_{rev_counter}"
        return schemas.ConfigResult(ok=True, revision=server_state["revision"])

    rcon.get_config = fake_get_config
    rcon.update_config = fake_update_config

    vips_136 = [f"76561198000000{i:03d}" for i in range(136)]
    bans_50 = [f"76561198900000{i:03d}" for i in range(50)]

    # Run both concurrently
    await asyncio.gather(
        rcon.sync_reserved_slots(vips_136),
        rcon.sync_banned_slots(bans_50)
    )

    final_text = server_state["text"]
    reserved_lines = [l for l in final_text.split('\n') if l.startswith('.DefaultReservedPlayerIds=')]
    banned_lines = [l for l in final_text.split('\n') if l.startswith('.DefaultBannedPlayerIds=')]

    # Assert 100% preservation: 136 VIPs and 50 bans coexist with zero data loss!
    assert len(reserved_lines) == 136
    assert len(banned_lines) == 50
    assert "!DefaultReservedPlayerIds=ClearArray" in final_text
    assert "!DefaultBannedPlayerIds=ClearArray" in final_text


@pytest.mark.asyncio
async def test_server_service_add_remove_reserved_slot_preserves_db_vips(session: AsyncSession, mocker):
    """
    Infallibility Test:
    add_reserved_slot and remove_reserved_slot must query active DB memberships
    and NEVER overwrite ServerSettings.ini with only the RCON in-memory list.
    """
    captured_slots = None

    async def fake_sync(slots):
        nonlocal captured_slots
        captured_slots = slots

    mocker.patch.object(RCONClient, "sync_reserved_slots", side_effect=fake_sync)

    # Seed 3 active DB VIPs
    for i in range(3):
        m = Membership(
            steam_id=f"7656119800000001{i}",
            membership_type="VIP_COMUN",
            is_active=True
        )
        session.add(m)
    await session.commit()

    # Add a new reserved slot manually
    new_slot = "76561198999999999"
    await ServerService.add_reserved_slot(new_slot, session=session)

    assert captured_slots is not None
    # All 3 seeded DB VIPs + new slot must be present!
    assert len(captured_slots) == 4
    assert new_slot in captured_slots
    assert "76561198000000010" in captured_slots

    # Remove the slot manually
    await ServerService.remove_reserved_slot(new_slot, session=session)
    assert len(captured_slots) == 3
    assert new_slot not in captured_slots
    assert "76561198000000010" in captured_slots


