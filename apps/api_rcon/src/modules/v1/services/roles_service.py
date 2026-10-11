from typing import Any

from fastapi import HTTPException
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_config import BOT_SETTINGS

from src.connections.databases.db import Membership, MembershipType, Player, Role, PlayerRole
from src.modules.v1.schemas.dtos import RoleRegisterRequest


class RolesService:
    @staticmethod
    async def _require_manual_management(role: Role, session: AsyncSession) -> None:
        """Keep manual role endpoints from changing membership-owned benefits."""
        if BOT_SETTINGS.DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED:
            return

        protected = role.role_type.strip().upper() == "VIP"
        if not protected:
            protected = (await session.exec(select(MembershipType.id).where(
                MembershipType.role_id == role.id,
            ).limit(1))).first() is not None
        if not protected:
            protected = (await session.exec(select(Membership.id).where(or_(
                Membership.role_granted_id == role.id,
                Membership.special_role_id == role.id,
            )).limit(1))).first() is not None
        if protected:
            raise HTTPException(
                status_code=409,
                detail="Los roles de membresía se administran desde Laracord. Usá los comandos /membership para gestionar sus beneficios.",
            )

    @staticmethod
    async def validate_manual_role_change(role_identifier: str, session: AsyncSession) -> None:
        """Validate reward fulfillment before spending points or creating a voucher."""
        role = await RolesService._find_role(role_identifier, session)
        if not role:
            raise HTTPException(status_code=404, detail=f"Role code or discord_role_id '{role_identifier}' not registered")
        await RolesService._require_manual_management(role, session)

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
            
        await RolesService._require_manual_management(role, session)

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
            
        await RolesService._require_manual_management(role, session)

        player_role = (await session.exec(select(PlayerRole).where(PlayerRole.steam_id == steam_id, PlayerRole.role_id == role.id))).first()
        if not player_role:
            raise HTTPException(status_code=404, detail="Player does not have this role")
            
        await session.delete(player_role)
        await session.commit()
        return {"ok": True, "message": f"Role '{role.code}' removed from player"}
