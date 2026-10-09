from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_schemas import v1 as schemas

from src.connections.databases.db import get_session
from src.modules.v1.services.squads_service import SquadsService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Squads"], prefix="/db/squads")

@router.post("", response_model=dict[str, Any], dependencies=[Depends(verify_api_key_guard)])
async def create_squad(name: str, tag: str, leader_steam_id: str, session: AsyncSession = Depends(get_session)):
    squad = await SquadsService.create_squad(name, tag, leader_steam_id, session)
    return {"id": squad.id, "name": squad.name, "tag": squad.tag}

@router.get("/leaderboard", response_model=list[dict[str, Any]])
async def get_squad_leaderboard(sort_by: str = "kills", session: AsyncSession = Depends(get_session)):
    squads = await SquadsService.get_leaderboard(sort_by, session)
    return [
        {
            "name": s.name, 
            "tag": s.tag, 
            "total_kills": s.total_kills, 
            "total_deaths": s.total_deaths, 
            "total_cash_earned": s.total_cash_earned, 
            "total_matches_played": s.total_matches_played
        }
        for s in squads
    ]

@router.get("/by-tag/{tag}", response_model=dict[str, Any])
async def get_squad_by_tag(tag: str, session: AsyncSession = Depends(get_session)):
    squad = await SquadsService.get_squad_by_name_or_tag(tag, session)
    return {
        "id": squad.id, 
        "name": squad.name, 
        "tag": squad.tag, 
        "leader_steam_id": squad.leader_steam_id, 
        "total_kills": squad.total_kills, 
        "total_deaths": squad.total_deaths, 
        "total_cash_earned": squad.total_cash_earned,
        "total_matches_played": squad.total_matches_played
    }

@router.get("/by-player/{steam_id}", response_model=list[dict[str, Any]])
async def get_player_squads(steam_id: str, session: AsyncSession = Depends(get_session)):
    squads = await SquadsService.get_player_squads(steam_id, session)
    return [
        {
            "id": squad.id, 
            "name": squad.name, 
            "tag": squad.tag, 
            "leader_steam_id": squad.leader_steam_id, 
            "total_kills": squad.total_kills, 
            "total_deaths": squad.total_deaths, 
            "total_cash_earned": squad.total_cash_earned,
            "total_matches_played": squad.total_matches_played
        }
        for squad in squads
    ]

@router.get("/{squad_id}/members", response_model=list[dict[str, Any]])
async def get_squad_members(squad_id: str, session: AsyncSession = Depends(get_session)):
    players = await SquadsService.get_squad_members(squad_id, session)
    return [{"steam_id": p.steam_id, "in_game_name": p.in_game_name, "discord_id": p.discord_id} for p in players]

@router.get("/{squad_id}/internal-leaderboard", response_model=list[dict[str, Any]])
async def get_squad_internal_leaderboard(squad_id: str, sort_by: str = "kills", session: AsyncSession = Depends(get_session)):
    return await SquadsService.get_squad_internal_leaderboard(squad_id, sort_by, session)

@router.post("/{squad_id}/members", response_model=schemas.Ok, dependencies=[Depends(verify_api_key_guard)])
async def add_squad_member(squad_id: str, steam_id: str, session: AsyncSession = Depends(get_session)):
    await SquadsService.add_member(squad_id, steam_id, session)
    return {"status": "ok", "message": "Miembro añadido"}

@router.delete("/{squad_id}/members/{steam_id}", response_model=schemas.Ok, dependencies=[Depends(verify_api_key_guard)])
async def remove_squad_member(squad_id: str, steam_id: str, session: AsyncSession = Depends(get_session)):
    await SquadsService.remove_member(squad_id, steam_id, session)
    return {"status": "ok", "message": "Miembro removido"}

@router.delete("/{squad_id}", response_model=schemas.Ok, dependencies=[Depends(verify_api_key_guard)])
async def disband_squad(squad_id: str, session: AsyncSession = Depends(get_session)):
    await SquadsService.disband_squad(squad_id, session)
    return {"status": "ok", "message": "Pelotón disuelto"}
