from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_schemas import v1 as schemas

from src.connections.databases.db import get_session
from src.modules.v1.schemas.dtos import RoleRegisterRequest
from src.modules.v1.services.roles_service import RolesService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Roles"])

@router.post("/db/roles", dependencies=[Depends(verify_api_key_guard)])
async def register_role(req: RoleRegisterRequest, session: AsyncSession = Depends(get_session)):
    return await RolesService.register_role(req, session)

@router.get("/db/roles", dependencies=[Depends(verify_api_key_guard)])
async def get_all_roles(session: AsyncSession = Depends(get_session)):
    return await RolesService.get_all_roles(session)

@router.get("/db/roles/{role_id}/players", dependencies=[Depends(verify_api_key_guard)])
async def get_players_by_role(role_id: str, session: AsyncSession = Depends(get_session)):
    return await RolesService.get_players_by_role(role_id, session)

@router.post("/db/players/{steam_id}/roles/{role_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def add_special_role(steam_id: str, role_id: str, session: AsyncSession = Depends(get_session)):
    return await RolesService.add_special_role(steam_id, role_id, session)

@router.delete("/db/players/{steam_id}/roles/{role_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def remove_special_role(steam_id: str, role_id: str, session: AsyncSession = Depends(get_session)):
    return await RolesService.remove_special_role(steam_id, role_id, session)
