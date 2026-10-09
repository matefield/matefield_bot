from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_schemas import v1 as schemas

from src.connections.apis.steam import get_player_summary
from src.connections.databases.db import get_session
from src.modules.v1.schemas.dtos import (
    EditPlayerRequest,
    LinkAccountRequest,
    UnlinkAccountRequest,
)
from src.modules.v1.services.players_service import PlayersService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Players"])

@router.get("/steam/player/{steam_id}", dependencies=[Depends(verify_api_key_guard)])
async def get_steam_player(steam_id: str):
    return await get_player_summary(steam_id)

@router.get("/steam/players", dependencies=[Depends(verify_api_key_guard)])
async def get_steam_players_batch(steam_ids: str):
    return await PlayersService.get_steam_players_batch(steam_ids)

@router.post("/db/players/link", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def link_account(req: LinkAccountRequest, session: AsyncSession = Depends(get_session)):
    return await PlayersService.link_account(req, session)

@router.post("/db/players/unlink", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def unlink_account(req: UnlinkAccountRequest, session: AsyncSession = Depends(get_session)):
    return await PlayersService.unlink_account(req, session)

@router.get("/db/players/discord/{discord_id}", dependencies=[Depends(verify_api_key_guard)])
async def get_player_by_discord(discord_id: str, session: AsyncSession = Depends(get_session)):
    return await PlayersService.get_by_discord(discord_id, session)

@router.get("/db/players/steam/{steam_id}", dependencies=[Depends(verify_api_key_guard)])
async def get_player_by_steam(steam_id: str, session: AsyncSession = Depends(get_session)):
    return await PlayersService.get_by_steam(steam_id, session)

@router.get("/db/players/steam/{steam_id}/stats", dependencies=[Depends(verify_api_key_guard)])
async def get_player_stats(steam_id: str, session: AsyncSession = Depends(get_session)):
    return await PlayersService.get_stats(steam_id, session)

@router.post("/db/players/steam/{steam_id}/welcome-message", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def set_welcome_message(steam_id: str, req: schemas.MessageRequest, session: AsyncSession = Depends(get_session)):
    return await PlayersService.set_welcome_message(steam_id, req.message, session)

@router.put("/db/players/{steam_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def edit_player(steam_id: str, req: EditPlayerRequest, session: AsyncSession = Depends(get_session)):
    return await PlayersService.edit_player(steam_id, req, session)

@router.get("/db/players", dependencies=[Depends(verify_api_key_guard)])
async def get_paginated_players(page: int = 1, limit: int = 10, linked: str = "all", session: AsyncSession = Depends(get_session)):
    return await PlayersService.get_paginated_players(page, limit, linked, session)
