import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from src.connections.databases.db import Squad, SquadMember, Player
from src.modules.v1.services.squads_service import SquadsService

@pytest.mark.asyncio
async def test_create_squad(session: AsyncSession):
    player = Player(steam_id="76561198000000001", in_game_name="Leader")
    session.add(player)
    await session.commit()

    squad = await SquadsService.create_squad("Los Halcones", "HALC", "76561198000000001", session)
    assert squad.name == "Los Halcones"
    assert squad.tag == "HALC"
    assert squad.leader_steam_id == "76561198000000001"

    # Check member added
    member = (await session.exec(select(SquadMember).where(SquadMember.steam_id == "76561198000000001"))).first()
    assert member is not None
    assert member.squad_id == squad.id

@pytest.mark.asyncio
async def test_create_squad_already_in_squad(session: AsyncSession):
    player1 = Player(steam_id="76561198000000001", in_game_name="Leader1")
    player2 = Player(steam_id="76561198000000002", in_game_name="Leader2")
    session.add_all([player1, player2])
    await session.commit()

    await SquadsService.create_squad("Los Halcones", "HALC", "76561198000000001", session)

    with pytest.raises(HTTPException) as exc:
        await SquadsService.create_squad("Otro Pelotón", "OTRO", "76561198000000001", session)
    assert exc.value.status_code == 400
    assert "Ya perteneces a un pelotón" in str(exc.value.detail)

@pytest.mark.asyncio
async def test_create_squad_name_taken(session: AsyncSession):
    player1 = Player(steam_id="76561198000000001", in_game_name="Leader1")
    player2 = Player(steam_id="76561198000000002", in_game_name="Leader2")
    session.add_all([player1, player2])
    await session.commit()

    await SquadsService.create_squad("Los Halcones", "HALC", "76561198000000001", session)

    with pytest.raises(HTTPException) as exc:
        await SquadsService.create_squad("Los Halcones", "HAL2", "76561198000000002", session)
    assert exc.value.status_code == 400
    assert "El nombre o tag del pelotón ya está en uso" in str(exc.value.detail)

@pytest.mark.asyncio
async def test_leave_squad(session: AsyncSession):
    player1 = Player(steam_id="76561198000000001", in_game_name="Leader")
    player2 = Player(steam_id="76561198000000002", in_game_name="Member")
    session.add_all([player1, player2])
    await session.commit()

    squad = await SquadsService.create_squad("Los Halcones", "HALC", "76561198000000001", session)
    await SquadsService.add_member(squad.id, "76561198000000002", session)

    # Leave squad
    await SquadsService.remove_member(squad.id, "76561198000000002", session)
    member = (await session.exec(select(SquadMember).where(SquadMember.steam_id == "76561198000000002"))).first()
    assert member is None
