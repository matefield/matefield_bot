from typing import Any

from fastapi import HTTPException
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Player, PlayerRole, Role
from src.modules.v1.schemas.dtos import RoleRegisterRequest


class RolesService:
    @staticmethod
    async def _find_role(role_identifier: str, session: AsyncSession) -> Role | None:
        clean_id = role_identifier.strip()
        conditions = [
            func.upper(Role.code) == clean_id.upper(),
            Role.discord_role_id == clean_id,
            func.upper(Role.name) == clean_id.upper()
        ]
        if clean_id.isdigit() and len(clean_id) < 10:
            conditions.append(Role.id == int(clean_id))
        return (await session.exec(select(Role).where(or_(*conditions)))).first()

    @staticmethod
    async def register_role(req: RoleRegisterRequest, session: AsyncSession) -> dict[str, Any]:
        normalized_code = req.code.strip().upper()
        existing = (await session.exec(select(Role).where(Role.code == normalized_code))).first()
        if existing:
            # If already exists, update name, role_type and discord_role_id
            existing.name = req.name.strip()
            existing.role_type = req.role_type.strip().upper()
            existing.discord_role_id = req.discord_role_id.strip() if req.discord_role_id else None
            session.add(existing)
            await session.commit()
            return {"ok": True, "message": f"Role '{normalized_code}' updated successfully"}
        
        # Free-form dynamic role type: allows standard (SYSTEM, VIP, SPECIAL, PUBLIC) or custom (e.g. MASTERCHEF)
        normalized_type = req.role_type.strip().upper()
        role = Role(
            code=normalized_code,
            name=req.name.strip(),
            role_type=normalized_type,
            discord_role_id=req.discord_role_id.strip() if req.discord_role_id else None
        )
        session.add(role)
        await session.commit()
        return {"ok": True, "message": f"Role '{normalized_code}' registered successfully as type '{normalized_type}'"}

    @staticmethod
    async def get_all_roles(session: AsyncSession) -> list[dict[str, Any]]:
        roles = (await session.exec(select(Role).order_by(Role.id))).all()
        return [
            {
                "code": r.code,
                "name": r.name,
                "role_type": r.role_type,
                "discord_role_id": r.discord_role_id
            }
            for r in roles
        ]

    @staticmethod
    async def get_players_by_role(role_id: str, session: AsyncSession) -> list[dict[str, Any]]:
        role = await RolesService._find_role(role_id, session)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        stmt = select(Player).join(PlayerRole).where(PlayerRole.role_id == role.id)
        players = (await session.exec(stmt)).all()
        
        return [
            {
                "steam_id": p.steam_id,
                "discord_id": p.discord_id,
                "in_game_name": p.in_game_name
            }
            for p in players
        ]

    @staticmethod
    async def add_special_role(steam_id: str, role_id: str, session: AsyncSession) -> dict[str, Any]:
        player = await session.get(Player, steam_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
            
        role = await RolesService._find_role(role_id, session)
        if not role:
            raise HTTPException(status_code=404, detail=f"Role code or discord_role_id '{role_id}' not registered")
            
        player_role = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == steam_id, PlayerRole.role_id == role.id))).first()
        if player_role:
            return {"ok": True, "message": "Player already has this role"}
            
        assert role.id is not None
        player_role = PlayerRole(steam_id=steam_id, role_id=role.id)
        session.add(player_role)
        from sqlalchemy.exc import IntegrityError
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"ok": True, "message": "Player already has this role"}
        return {"ok": True, "message": f"Role '{role.code}' added to player"}

    @staticmethod
    async def remove_special_role(steam_id: str, role_id: str, session: AsyncSession) -> dict[str, Any]:
        role = await RolesService._find_role(role_id, session)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
            
        player_role = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == steam_id, PlayerRole.role_id == role.id))).first()
        if not player_role:
            raise HTTPException(status_code=404, detail="Player does not have this role")
            
        await session.delete(player_role)
        await session.commit()
        return {"ok": True, "message": f"Role '{role.code}' removed from player"}
