"""
Wardogs RCON API — Application entrypoint.

Startup sequence:
  1. Load environment variables.
  2. Configure structured logging.
  3. Register FastAPI app with lifespan that manages background tasks:
     - RCON polling / game-sync engine (poll_rcon)
     - Membership expiry + Discord role sync (db_maintenance_loop, every 5 min)
     - Automated SQL backups (db_backup_loop, every 12 h)
  4. Mount static files and include API routers.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete
from sqlmodel.ext.asyncio.session import AsyncSession

load_dotenv()

from wardogs_config import ENVIRONMENT_SETTINGS

from src.connections.apis.rcon import RCONManager
from src.connections.databases.db import SteamLinkRedemption, engine
from src.modules import V1_ROUTER
from src.modules.v1.routers.discord_steam_link import (
    router as discord_steam_link_router,
)
from src.modules.v1.services.backup_service import create_database_sql_backup
from src.modules.v1.services.memberships_service import MembershipsService
from src.modules.v1.services.membership_deliveries_service import MembershipDeliveriesService
from src.sync_engine import poll_rcon

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wardogs.api")

# ---------------------------------------------------------------------------
# Timing constants (seconds)
# ---------------------------------------------------------------------------
_MAINTENANCE_INTERVAL = 300    # 5 minutes
_BACKUP_INITIAL_DELAY = 30     # warm-up before first backup
_BACKUP_INTERVAL = 43_200      # 12 hours

# ---------------------------------------------------------------------------
# Background task handles (module-level so lifespan can cancel them)
# ---------------------------------------------------------------------------
polling_task: asyncio.Task | None = None
maintenance_task: asyncio.Task | None = None
backup_task: asyncio.Task | None = None


async def db_maintenance_loop() -> None:
    """Periodically expire stale steam-link tokens and sync memberships/roles."""
    while True:
        try:
            async with AsyncSession(engine) as session:
                await session.exec(
                    delete(SteamLinkRedemption).where(
                        SteamLinkRedemption.expires_at < int(time.time())
                    )
                )
                await session.commit()
                await MembershipsService.sync_memberships_logic(session)
            await MembershipDeliveriesService.retry_pending(engine)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("[Maintenance] Error during maintenance cycle", exc_info=exc)
        await asyncio.sleep(_MAINTENANCE_INTERVAL)


async def db_backup_loop() -> None:
    """Creates automated SQL backups every 12 hours, with a 30-second startup delay."""
    try:
        await asyncio.sleep(_BACKUP_INITIAL_DELAY)
    except asyncio.CancelledError:
        return
    while True:
        try:
            async with AsyncSession(engine) as session:
                await create_database_sql_backup(session)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("[Backup] Error creating automated SQL backup", exc_info=exc)
        await asyncio.sleep(_BACKUP_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: starts background tasks on startup, cancels them on shutdown."""
    global polling_task, maintenance_task, backup_task
    polling_task = asyncio.create_task(poll_rcon(), name="rcon_poll")
    maintenance_task = asyncio.create_task(db_maintenance_loop(), name="db_maintenance")
    backup_task = asyncio.create_task(db_backup_loop(), name="db_backup")
    logger.info("Application background services started.")
    yield
    tasks = [t for t in (polling_task, maintenance_task, backup_task) if t is not None]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await RCONManager.close_all()
    logger.info("Application background services and RCON connection pools shut down.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Wardogs RCON API",
    version="1.4.0",
    lifespan=lifespan,
)

# Static files (optional — only mounted when the directory exists)
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/api/static", StaticFiles(directory=str(STATIC_DIR)), name="api_static")

app.include_router(V1_ROUTER, prefix="/api")
app.include_router(discord_steam_link_router)
# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    host = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.SERVER_HOST
    port = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.SERVER_PORT
    uvicorn.run(app, host=host, port=port)
