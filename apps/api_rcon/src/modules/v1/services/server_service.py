"""
ServerService — façade over RCONManager for game-server commands.

All public methods require an AsyncSession and resolve the active RCON
server through RCONManager (DB-configured, falling back to .env).

This eliminates the stale ``rcon_client`` pattern where every call used
the .env-hardcoded server regardless of what was stored in the database.
"""
import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_schemas import v1 as schemas

from src.connections.apis.rcon import RCONClient, RCONManager

logger = logging.getLogger("wardogs.server_service")


class ServerService:
    @staticmethod
    async def _get_client(session: AsyncSession) -> tuple[Any, RCONClient]:
        """Resolves the default RCON client from DB (falls back to .env config)."""
        return await RCONManager.get_default_server(session)

    @staticmethod
    async def get_status(session: AsyncSession) -> schemas.Status:
        _, client = await RCONManager.get_default_server(session)
        return await client.get_status()

    @staticmethod
    async def get_players(session: AsyncSession) -> schemas.Players1:
        _, client = await RCONManager.get_default_server(session)
        return await client.get_players()

    @staticmethod
    async def get_audit_logs(limit: int = 50, *, session: AsyncSession) -> schemas.Audit:
        _, client = await RCONManager.get_default_server(session)
        return await client.get_audit_logs(limit)

    @staticmethod
    async def broadcast(message: str, *, session: AsyncSession) -> None:
        """Broadcasts a message to ALL active RCON servers."""
        active_servers = await RCONManager.get_all_active_servers(session)
        for s_info, client in active_servers:
            try:
                await client.broadcast(message)
            except Exception as exc:
                logger.warning("Failed to broadcast to %s: %s", s_info.name, exc)

    @staticmethod
    async def send_player_message(steam_id: str, message: str, *, session: AsyncSession) -> None:
        active_servers = await RCONManager.get_all_active_servers(session)
        for s_info, client in active_servers:
            try:
                await client.send_player_message(steam_id, message)
            except Exception as exc:
                logger.debug("Failed to send player message on %s: %s", s_info.name, exc)

    @staticmethod
    async def kick_player(steam_id: str, reason: str, *, session: AsyncSession) -> None:
        active_servers = await RCONManager.get_all_active_servers(session)
        for s_info, client in active_servers:
            try:
                await client.kick_player(steam_id, reason)
            except Exception as exc:
                logger.debug("Failed to kick player on %s: %s", s_info.name, exc)

    @staticmethod
    async def ban_player(steam_id: str, reason: str, *, session: AsyncSession) -> None:
        active_servers = await RCONManager.get_all_active_servers(session)
        for s_info, client in active_servers:
            try:
                await client.ban_player(steam_id, reason)
            except Exception as exc:
                logger.debug("Failed to ban player on %s: %s", s_info.name, exc)

    @staticmethod
    async def switch_faction(steam_id: str, faction: str, *, session: AsyncSession) -> None:
        _, client = await RCONManager.get_default_server(session)
        await client.switch_faction(steam_id, faction)

    @staticmethod
    async def get_reserved_slots(*, session: AsyncSession) -> schemas.ReservedSlots:
        _, client = await RCONManager.get_default_server(session)
        return await client.get_reserved_slots()

    @staticmethod
    async def add_reserved_slot(steam_id: str, *, session: AsyncSession) -> None:
        from sqlmodel import select

        from src.connections.databases.db import Membership

        db_stmt = select(Membership.steam_id).where(Membership.is_active == True).order_by(Membership.steam_id)
        db_slots = set((await session.exec(db_stmt)).all())
        db_slots.add(steam_id)
        target_slots = sorted(list(db_slots))

        active_servers = await RCONManager.get_all_active_servers(session)
        for s_info, client in active_servers:
            try:
                await client.sync_reserved_slots(target_slots)
            except Exception as exc:
                logger.warning("Failed to add reserved slot on %s: %s", s_info.name, exc)

    @staticmethod
    async def remove_reserved_slot(steam_id: str, *, session: AsyncSession) -> None:
        from sqlmodel import select

        from src.connections.databases.db import Membership

        db_stmt = select(Membership.steam_id).where(Membership.is_active == True).order_by(Membership.steam_id)
        db_slots = set((await session.exec(db_stmt)).all())
        db_slots.discard(steam_id)
        target_slots = sorted(list(db_slots))

        active_servers = await RCONManager.get_all_active_servers(session)
        for s_info, client in active_servers:
            try:
                await client.sync_reserved_slots(target_slots)
            except Exception as exc:
                logger.warning("Failed to remove reserved slot on %s: %s", s_info.name, exc)

    @staticmethod
    async def update_config(revision: str, new_text: str, *, session: AsyncSession) -> schemas.ConfigResult:
        _, client = await RCONManager.get_default_server(session)
        return await client.update_config(revision, new_text)
