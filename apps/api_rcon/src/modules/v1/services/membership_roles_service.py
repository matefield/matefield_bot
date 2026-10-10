"""Guild-specific role configuration; Discord permissions remain the bot's concern."""
from datetime import datetime, timezone
import logging
from typing import List, Optional

from fastapi import HTTPException
from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Membership, MembershipType, Role, RoleDiscordBinding
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import (
    ConfigureMembershipRoleRequest, MembershipRoleConfiguration,
    UnassignMembershipRoleRequest, MembershipRoleUnassignment,
)

logger = logging.getLogger("wardogs.memberships")


class MembershipRolesService:
    @staticmethod
    def require_enabled_guild(guild_id: str) -> None:
        settings = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS
        configured = settings.DISCORD_GUILD_IDS
        if configured is None or not configured.strip():
            configured = settings.DISCORD_GUILD_ID or ""
        enabled = {value.strip() for value in configured.split(",") if value.strip()}
        if guild_id not in enabled:
            raise HTTPException(status_code=403, detail="Este servidor de Discord no está habilitado para gestionar membresías.")

    @staticmethod
    async def _membership_role(membership_type: str, session: AsyncSession, lock: bool = False,
                               require_active: bool = True):
        m_type = (await session.exec(select(MembershipType).where(
            func.upper(MembershipType.code) == membership_type.strip().upper()
        ))).first()
        if not m_type:
            raise HTTPException(status_code=404, detail="Tipo de membresía no encontrado.")
        if require_active and not m_type.is_active:
            raise HTTPException(status_code=400, detail="Seleccioná un tipo de membresía activo.")
        role_statement = select(Role).where(Role.id == m_type.role_id)
        if lock:
            role_statement = role_statement.with_for_update()
        role = (await session.exec(role_statement)).first() if m_type.role_id else None
        if not role:
            raise HTTPException(status_code=400, detail={"code": "membership_type_role_missing"})
        return m_type, role

    @staticmethod
    async def _binding(guild_id: str, role_id: int, session: AsyncSession) -> Optional[RoleDiscordBinding]:
        return (await session.exec(select(RoleDiscordBinding).where(
            RoleDiscordBinding.guild_id == guild_id, RoleDiscordBinding.role_id == role_id,
        ).execution_options(populate_existing=True))).first()

    @staticmethod
    def _response(m_type: MembershipType, binding: RoleDiscordBinding, changed: bool = False) -> MembershipRoleConfiguration:
        return MembershipRoleConfiguration(
            guild_id=binding.guild_id, membership_type=m_type.code,
            membership_type_name=m_type.name, role_id=binding.role_id,
            discord_role_id=binding.discord_role_id, configured_by=binding.configured_by,
            changed=changed,
        )

    @staticmethod
    async def get(guild_id: str, membership_type: str, session: AsyncSession) -> MembershipRoleConfiguration:
        MembershipRolesService.require_enabled_guild(guild_id)
        m_type, role = await MembershipRolesService._membership_role(membership_type, session)
        binding = await MembershipRolesService._binding(guild_id, role.id, session)
        if not binding:
            raise HTTPException(status_code=404, detail="Esta membresía todavía no tiene un rol de Discord configurado en este servidor.")
        return MembershipRolesService._response(m_type, binding)

    @staticmethod
    async def configure(guild_id: str, membership_type: str, req: ConfigureMembershipRoleRequest, session: AsyncSession) -> MembershipRoleConfiguration:
        MembershipRolesService.require_enabled_guild(guild_id)
        m_type, role = await MembershipRolesService._membership_role(membership_type, session, lock=True)
        binding = await MembershipRolesService._binding(guild_id, role.id, session)
        if binding and binding.discord_role_id == req.discord_role_id:
            return MembershipRolesService._response(m_type, binding)
        legacy_guild = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.DISCORD_GUILD_ID
        replaces_legacy = (not binding and guild_id == legacy_guild and role.discord_role_id
                           and role.discord_role_id != req.discord_role_id)
        if (binding or replaces_legacy) and await MembershipRolesService._has_active_memberships(role.id, session):
            raise HTTPException(status_code=409, detail="No se puede reemplazar este rol mientras haya membresías vigentes que lo otorgan. La migración de roles existentes requiere una operación explícita.")
        if binding:
            now = datetime.now(timezone.utc)
            binding.discord_role_id = req.discord_role_id
            binding.configured_by = req.actor_id
            binding.updated_at = now
        else:
            binding = RoleDiscordBinding(role_id=role.id, guild_id=guild_id,
                                         discord_role_id=req.discord_role_id, configured_by=req.actor_id)
        session.add(binding)
        await session.commit()
        await session.refresh(binding)
        return MembershipRolesService._response(m_type, binding, changed=True)

    @staticmethod
    async def unassign(guild_id: str, membership_type: str, req: UnassignMembershipRoleRequest,
                       session: AsyncSession) -> MembershipRoleUnassignment:
        """Remove only this guild binding after serializing with configuration and creation."""
        MembershipRolesService.require_enabled_guild(guild_id)
        m_type, role = await MembershipRolesService._membership_role(
            membership_type, session, lock=True, require_active=False,
        )
        binding = await MembershipRolesService._binding(guild_id, role.id, session)
        if binding:
            if await MembershipRolesService._has_active_memberships(role.id, session):
                raise HTTPException(status_code=409, detail={"code": "membership_role_in_use"})
            shared_type = (await session.exec(select(MembershipType.id).where(
                MembershipType.role_id == role.id, MembershipType.id != m_type.id,
            ).limit(1))).first()
            if shared_type is not None:
                raise HTTPException(status_code=409, detail={"code": "membership_role_shared"})

        response = MembershipRoleUnassignment(
            guild_id=guild_id, membership_type=m_type.code, membership_type_name=m_type.name,
            role_id=role.id, discord_role_id=binding.discord_role_id if binding else None,
            actor_id=req.actor_id, changed=binding is not None,
        )
        if binding:
            await session.delete(binding)
        await session.commit()
        logger.info(
            "membership_role_unassignment actor_id=%s guild_id=%s membership_type=%s "
            "role_id=%s previous_discord_role_id=%s changed=%s",
            response.actor_id, response.guild_id, response.membership_type,
            response.role_id, response.discord_role_id, response.changed,
            extra={"actor_id": response.actor_id, "guild_id": response.guild_id,
                   "membership_type": response.membership_type, "role_id": response.role_id,
                   "previous_discord_role_id": response.discord_role_id, "changed": response.changed},
        )
        return response

    @staticmethod
    async def _has_active_memberships(role_id: int, session: AsyncSession) -> bool:
        now = datetime.now(timezone.utc)
        active = (await session.exec(
            select(Membership.id)
            .outerjoin(MembershipType, func.upper(Membership.membership_type) == func.upper(MembershipType.code))
            .where(
                or_((Membership.is_active == True) & (Membership.start_time <= now), Membership.is_scheduled == True),
                or_(Membership.end_time == None, Membership.end_time > now),
                or_(Membership.role_granted_id == role_id, Membership.special_role_id == role_id,
                    (Membership.role_granted_id == None) & (MembershipType.role_id == role_id)),
            ).limit(1)
        )).first()
        return active is not None

    @staticmethod
    async def resolve_roles(guild_id: str, role_ids: List[int], session: AsyncSession, lock: bool = True) -> List[str]:
        """Resolve every required logical role without falling back to global IDs."""
        MembershipRolesService.require_enabled_guild(guild_id)
        unique_ids = list(dict.fromkeys(role_ids))
        if lock:
            # Configuration takes the same logical-role locks. Resolve all roles in
            # stable order before creation, including the optional special role.
            await session.exec(select(Role).where(col(Role.id).in_(unique_ids)).order_by(Role.id).with_for_update())
        bindings = (await session.exec(select(RoleDiscordBinding).where(
            RoleDiscordBinding.guild_id == guild_id, col(RoleDiscordBinding.role_id).in_(unique_ids),
        ).execution_options(populate_existing=True))).all()
        by_role = {binding.role_id: binding.discord_role_id for binding in bindings}
        if any(role_id not in by_role for role_id in unique_ids):
            raise HTTPException(status_code=409, detail={"code": "membership_role_configuration_missing"})
        return list(dict.fromkeys(by_role[role_id] for role_id in unique_ids))
