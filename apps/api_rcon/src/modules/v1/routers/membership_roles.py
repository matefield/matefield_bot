"""Authenticated configuration of membership roles in explicitly enabled guilds."""
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import get_session
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.security.guard import verify_api_key_guard
from wardogs_schemas.dtos import DiscordSnowflake, ConfigureMembershipRoleRequest, MembershipRoleConfiguration

router = APIRouter(prefix="/discord/guilds", tags=["Discord Membership Roles"],
                   dependencies=[Depends(verify_api_key_guard)])


@router.get("/{guild_id}/membership-types/{membership_type}/role", response_model=MembershipRoleConfiguration)
async def get_membership_role(guild_id: DiscordSnowflake, membership_type: str,
                              session: AsyncSession = Depends(get_session)):
    return await MembershipRolesService.get(guild_id, membership_type, session)


@router.put("/{guild_id}/membership-types/{membership_type}/role", response_model=MembershipRoleConfiguration)
async def configure_membership_role(guild_id: DiscordSnowflake, membership_type: str,
                                    req: ConfigureMembershipRoleRequest,
                                    session: AsyncSession = Depends(get_session)):
    return await MembershipRolesService.configure(guild_id, membership_type, req, session)
