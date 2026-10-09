from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import get_session
from src.modules.v1.services.memberships_service import MembershipsService
from src.modules.v1.routers import (
    server_router,
    players_router,
    memberships_router,
    roles_router,
    matches_router,
    config_router,
    rcon_servers_router,
    membership_types_router,
    membership_roles_router,
    auth_router,
    rewards_router,
)

router = APIRouter(prefix="/v1", tags=["v1"])

# Aggregate modular subrouters
router.include_router(server_router)
router.include_router(players_router)
router.include_router(memberships_router)
router.include_router(roles_router)
router.include_router(matches_router)
router.include_router(config_router)
router.include_router(rcon_servers_router)
router.include_router(membership_types_router)
router.include_router(membership_roles_router)
router.include_router(auth_router)
router.include_router(rewards_router)


# Compatibility exports for background maintenance tasks and external callers
async def sync_memberships(session: AsyncSession = Depends(get_session)):
    return await MembershipsService.sync_memberships_logic(session)

V1_ROUTER = router

__all__ = ["router", "V1_ROUTER", "sync_memberships"]
