import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.rcon import RCONManager
from src.connections.databases.db import Membership, RconServer
from src.modules.v1.schemas.dtos import CreateRconServerRequest, UpdateRconServerRequest

logger = logging.getLogger("wardogs.rcon_servers")


class RconServersService:
    @staticmethod
    async def list_servers(session: AsyncSession, check_health: bool = True) -> list[dict[str, Any]]:
        stmt = select(RconServer).order_by(col(RconServer.is_default).desc(), col(RconServer.id))
        servers = (await session.exec(stmt)).all()

        async def fetch_server_data(s: RconServer) -> dict[str, Any]:
            data: dict[str, Any] = {
                "id": s.id,
                "name": s.name,
                "ip": s.ip,
                "port": s.port,
                "scheme": s.scheme,
                "base_url": s.base_url,
                "is_active": s.is_active,
                "is_default": s.is_default,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "is_online": False,
                "current_map": None,
                "player_count": None,
                "max_players": None,
                "ping_ms": None,
            }

            if check_health and s.is_active:
                client = RCONManager.get_client_for_server(s)
                t0 = time.time()
                try:
                    status = await asyncio.wait_for(client.get_status(), timeout=2.0)
                    data["is_online"] = True
                    data["current_map"] = status.map
                    data["player_count"] = status.players.current if status.players else None
                    data["max_players"] = status.players.max if status.players else None
                    data["ping_ms"] = round((time.time() - t0) * 1000, 1)
                except Exception as e:
                    logger.debug(f"Health check failed for RCON server {s.name} ({s.base_url}): {e}")
                    data["is_online"] = False

            return data

        results = await asyncio.gather(*[fetch_server_data(s) for s in servers])
        return list(results)

    @staticmethod
    async def create_server(req: CreateRconServerRequest, session: AsyncSession) -> dict[str, Any]:
        # If set as default, unset other defaults
        if req.is_default:
            existing_defaults = (await session.exec(select(RconServer).where(RconServer.is_default == True))).all()
            for ed in existing_defaults:
                ed.is_default = False
                session.add(ed)

        server_name = req.name.strip() if req.name and req.name.strip() else ""

        # Auto-fill name by probing the RCON status if name was not provided
        if not server_name:
            target_url = f"{req.scheme}://{req.ip}:{req.port}"
            temp_client = RCONManager.get_client(base_url=target_url, password=req.password)
            try:
                status = await asyncio.wait_for(temp_client.get_status(), timeout=3.0)
                if status.serverName and status.serverName.strip():
                    server_name = status.serverName.strip()
            except Exception as e:
                logger.info(f"Could not auto-fetch serverName for {req.ip}:{req.port}: {e}")

        if not server_name:
            server_name = f"Servidor {req.ip}:{req.port}"

        now = datetime.now(UTC)
        server = RconServer(
            name=server_name,
            ip=req.ip.strip(),
            port=req.port,
            password=req.password,
            scheme=req.scheme.strip().lower(),
            is_active=req.is_active,
            is_default=req.is_default,
            created_at=now,
            updated_at=now,
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)

        return {
            "ok": True,
            "message": f"Servidor RCON '{server.name}' registrado exitosamente",
            "server": {
                "id": server.id,
                "name": server.name,
                "ip": server.ip,
                "port": server.port,
                "scheme": server.scheme,
                "base_url": server.base_url,
                "is_active": server.is_active,
                "is_default": server.is_default,
            }
        }

    @staticmethod
    async def get_server(server_id: int, session: AsyncSession) -> dict[str, Any]:
        server = await session.get(RconServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"Servidor RCON ID {server_id} no encontrado")
        return {
            "id": server.id,
            "name": server.name,
            "ip": server.ip,
            "port": server.port,
            "scheme": server.scheme,
            "base_url": server.base_url,
            "is_active": server.is_active,
            "is_default": server.is_default,
            "created_at": server.created_at.isoformat() if server.created_at else None,
            "updated_at": server.updated_at.isoformat() if server.updated_at else None,
        }

    @staticmethod
    async def update_server(server_id: int, req: UpdateRconServerRequest, session: AsyncSession) -> dict[str, Any]:
        server = await session.get(RconServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"Servidor RCON ID {server_id} no encontrado")

        if req.is_default is True and not server.is_default:
            existing_defaults = (await session.exec(select(RconServer).where(RconServer.is_default == True))).all()
            for ed in existing_defaults:
                ed.is_default = False
                session.add(ed)

        if req.name is not None:
            server.name = req.name.strip()
        if req.ip is not None:
            server.ip = req.ip.strip()
        if req.port is not None:
            server.port = req.port
        if req.password is not None:
            server.password = req.password
        if req.scheme is not None:
            server.scheme = req.scheme.strip().lower()
        if req.is_active is not None:
            server.is_active = req.is_active
        if req.is_default is not None:
            server.is_default = req.is_default

        server.updated_at = datetime.now(UTC)
        session.add(server)
        await session.commit()
        await session.refresh(server)

        return {
            "ok": True,
            "message": f"Servidor RCON ID {server.id} actualizado",
            "server": {
                "id": server.id,
                "name": server.name,
                "ip": server.ip,
                "port": server.port,
                "scheme": server.scheme,
                "base_url": server.base_url,
                "is_active": server.is_active,
                "is_default": server.is_default,
            }
        }

    @staticmethod
    async def delete_server(server_id: int, session: AsyncSession) -> dict[str, Any]:
        server = await session.get(RconServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"Servidor RCON ID {server_id} no encontrado")

        # Detach foreign keys in memberships and membership_types
        from sqlmodel import update

        from src.connections.databases.db import Membership, MembershipType
        await session.exec(
            update(Membership).where(Membership.server_id == server_id).values(server_id=None)
        )
        await session.exec(
            update(MembershipType).where(MembershipType.server_id == server_id).values(server_id=None)
        )

        was_default = server.is_default
        await session.delete(server)
        await session.flush()

        if was_default:
            next_server = (await session.exec(select(RconServer).where(RconServer.is_active == True))).first()
            if next_server:
                next_server.is_default = True
                session.add(next_server)

        await session.commit()
        return {"ok": True, "message": f"Servidor RCON '{server.name}' eliminado"}

    @staticmethod
    async def test_server(server_id: int, session: AsyncSession) -> dict[str, Any]:
        server = await session.get(RconServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"Servidor RCON ID {server_id} no encontrado")

        client = RCONManager.get_client_for_server(server)
        t0 = time.time()
        try:
            status = await asyncio.wait_for(client.get_status(), timeout=4.0)
            latency = round((time.time() - t0) * 1000, 1)
            return {
                "ok": True,
                "is_online": True,
                "latency_ms": latency,
                "server_id": server.id,
                "name": server.name,
                "server_name": status.serverName,
                "current_map": status.map,
                "player_count": status.players.current if status.players else None,
                "max_players": status.players.max if status.players else None,
                "match_seconds": status.matchSeconds
            }
        except Exception as e:
            return {
                "ok": False,
                "is_online": False,
                "server_id": server.id,
                "name": server.name,
                "error": str(e)
            }

    @staticmethod
    async def sync_all_servers(session: AsyncSession) -> dict[str, Any]:
        active_servers = await RCONManager.get_all_active_servers(session)

        ban_stmt = select(Ban.steam_id).where(Ban.is_active == True).distinct()
        ban_ids = list(set((await session.exec(ban_stmt)).all()))

        results = []
        for s_info, client in active_servers:
            if s_info.id is not None:
                vip_stmt = select(Membership.steam_id).where(
                    Membership.is_active == True,
                    or_(Membership.server_id == None, Membership.server_id == s_info.id)
                ).distinct()
            else:
                vip_stmt = select(Membership.steam_id).where(
                    Membership.is_active == True,
                    Membership.server_id == None
                ).distinct()
            vip_ids = list(set((await session.exec(vip_stmt)).all()))

            server_res: dict[str, Any] = {
                "server_id": s_info.id,
                "server_name": s_info.name,
                "base_url": s_info.base_url,
                "status": "SUCCESS",
                "vip_slots_synced": len(vip_ids),
                "bans_synced": len(ban_ids),
                "error": None
            }
            try:
                await client.sync_reserved_slots(vip_ids)
                await client.sync_banned_slots(ban_ids)
            except Exception as e:
                logger.warning(f"Error syncing {s_info.name}: {e}")
                server_res["status"] = "ERROR"
                server_res["error"] = str(e)
            results.append(server_res)

        return {
            "ok": True,
            "message": f"Sincronizados {len(active_servers)} servidores RCON",
            "results": results
        }
