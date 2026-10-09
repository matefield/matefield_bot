from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import get_session
from src.modules.v1.services.matches_service import MatchesService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Matches & Leaderboard"])

@router.get("/db/matches", dependencies=[Depends(verify_api_key_guard)])
async def get_paginated_matches(page: int = 1, limit: int = 10, session: AsyncSession = Depends(get_session)):
    return await MatchesService.get_paginated_matches(page, limit, session)

@router.get("/db/matches/latest", dependencies=[Depends(verify_api_key_guard)])
async def get_latest_match(session: AsyncSession = Depends(get_session)):
    return await MatchesService.get_latest_match(session)

@router.get("/db/leaderboard", dependencies=[Depends(verify_api_key_guard)])
async def get_leaderboard(metric: str = "kills", limit: int = 15, session: AsyncSession = Depends(get_session)):
    return await MatchesService.get_leaderboard(metric, limit, session)
