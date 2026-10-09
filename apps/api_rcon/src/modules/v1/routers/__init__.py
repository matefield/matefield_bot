from src.modules.v1.routers.server import router as server_router
from src.modules.v1.routers.players import router as players_router
from src.modules.v1.routers.memberships import router as memberships_router
from src.modules.v1.routers.roles import router as roles_router
from src.modules.v1.routers.matches import router as matches_router
from src.modules.v1.routers.config import router as config_router
from src.modules.v1.routers.rcon_servers import router as rcon_servers_router
from src.modules.v1.routers.membership_types import router as membership_types_router
from src.modules.v1.routers.auth import router as auth_router
from src.modules.v1.routers.rewards import router as rewards_router
from src.modules.v1.routers.membership_roles import router as membership_roles_router
__all__ = [
    "membership_roles_router",
    "server_router",
    "players_router",
    "memberships_router",
    "roles_router",
    "matches_router",
    "config_router",
    "rcon_servers_router",
    "membership_types_router",
    "auth_router",
    "rewards_router",
]


