import logging
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from sqlmodel import select, func, col, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Player, Membership, Role, PlayerRole, BotConfig, MembershipType, RoleDiscordBinding, RconServer, MembershipRemovalOperation, MembershipRenewalDelivery
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.connections.apis.rcon import RCONManager
from src.connections.apis.warcon import WarconClient
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import CreatedMembershipItem, MembershipDiscordDelivery, AddMembershipResponse
from src.modules.v1.schemas.dtos import AddMembershipRequest, EditMembershipRequest, CompensateRequest

logger = logging.getLogger("wardogs.memberships")

class MembershipsService:
    @staticmethod
    async def _require_no_pending_removal(steam_id: str, session: AsyncSession) -> None:
        pending = (await session.exec(select(MembershipRemovalOperation.operation_id).where(
            MembershipRemovalOperation.steam_id == steam_id,
            MembershipRemovalOperation.discord_roles_removed == False,
        ).limit(1))).first()
        if pending:
            raise HTTPException(status_code=409, detail={"code": "membership_removal_pending"})

    @staticmethod
    async def _require_no_pending_renewal_delivery(steam_id: str, session: AsyncSession) -> None:
        pending = (await session.exec(select(MembershipRenewalDelivery.id).join(
            Membership, MembershipRenewalDelivery.membership_id == Membership.id,
        ).where(
            Membership.steam_id == steam_id, MembershipRenewalDelivery.activated == True,
            MembershipRenewalDelivery.completed == False, MembershipRenewalDelivery.cancelled == False,
        ).limit(1))).first()
        if pending:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_delivery_pending"})

    @staticmethod
    async def _require_no_scheduled_renewal(steam_id: str, session: AsyncSession) -> None:
        """Legacy edits must not move a calendar already owned by a renewal receipt."""
        now = datetime.now(timezone.utc)
        pending = (await session.exec(select(Membership.id).outerjoin(
            MembershipRenewalDelivery, MembershipRenewalDelivery.membership_id == Membership.id,
        ).where(
            Membership.steam_id == steam_id,
            or_(Membership.is_scheduled == True,
                ((Membership.is_active == True) & or_(Membership.end_time == None, Membership.end_time > now)
                 & (MembershipRenewalDelivery.cancelled == False)),
                ((MembershipRenewalDelivery.phase == "END") & (MembershipRenewalDelivery.cancelled == False)
                 & (MembershipRenewalDelivery.completed == False))),
        ).limit(1))).first()
        if pending:
            raise HTTPException(status_code=409, detail={"code": "membership_renewals_pending"})

    @staticmethod
    async def add_membership(req: AddMembershipRequest, session: AsyncSession) -> Dict[str, Any]:
        if req.source == "DISCORD" and req.guild_id:
            MembershipRolesService.require_enabled_guild(req.guild_id)
        player = (await session.exec(select(Player).where(Player.steam_id == req.steam_id).with_for_update())).first()
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        discord_source = req.source == "DISCORD"
        # Preserve hashes of pre-guild requests while binding new operations to their guild.
        excluded = {"operation_id"} if req.guild_id else {"operation_id", "guild_id"}
        request_hash = hashlib.sha256(json.dumps(req.model_dump(exclude=excluded), sort_keys=True).encode()).hexdigest()
        if discord_source:
            previous = (await session.exec(select(Membership).where(
                Membership.creation_operation_id == req.operation_id
            ))).first()
            if previous:
                if previous.creation_request_hash != request_hash:
                    raise HTTPException(status_code=409, detail="Esta operación ya se utilizó con otros datos.")
                return await MembershipsService._deliver_discord_membership(previous, player, session, replayed=True, guild_id=req.guild_id)
        
        await MembershipsService._require_no_pending_renewal_delivery(req.steam_id, session)
        if discord_source:
            now = datetime.now(timezone.utc)
            active = (await session.exec(select(Membership.id).where(
                Membership.steam_id == req.steam_id, Membership.is_active == True,
                Membership.start_time <= now, or_(Membership.end_time == None, Membership.end_time > now),
            ).limit(1))).first()
            if active:
                raise HTTPException(status_code=409, detail={"code": "membership_already_active"})
            scheduled = (await session.exec(select(Membership.id).where(
                Membership.steam_id == req.steam_id, Membership.is_scheduled == True,
            ).limit(1))).first()
            if scheduled:
                raise HTTPException(status_code=409, detail={"code": "membership_renewal_already_scheduled"})
        else:
            # Legacy renewals cannot shorten or overlap a period already scheduled.
            await MembershipsService._require_no_scheduled_renewal(req.steam_id, session)

        norm_type = req.membership_type.strip().upper()
        # Different players compete for the same quota. Serialize that count and
        # insertion on the type row, in addition to the per-player renewal lock.
        m_type = (await session.exec(select(MembershipType).where(
            func.upper(MembershipType.code) == norm_type
        ).with_for_update().execution_options(populate_existing=True))).first()
        if discord_source:
            WarconClient().validate_configuration()
            if req.server_id is not None or (m_type and m_type.server_id is not None):
                raise HTTPException(status_code=400, detail="Las altas desde Discord usan el servidor global configurado en Warcon; todavía no admiten un servidor específico.")
            if not m_type or not m_type.is_active:
                raise HTTPException(status_code=400, detail="Seleccioná un tipo de membresía activo registrado en nuestro sistema.")
            if not MembershipsService._valid_discord_id(player.discord_id):
                raise HTTPException(status_code=400, detail="El jugador no tiene una cuenta de Discord válida vinculada.")
            role = (await session.exec(select(Role).where(Role.id == m_type.role_id))).first() if m_type.role_id else None
            if not role:
                raise HTTPException(status_code=400, detail={"code": "membership_type_role_missing"})
            if req.guild_id:
                await MembershipRolesService.resolve_roles(req.guild_id, [role.id], session, lock=False)
            elif not MembershipsService._valid_discord_id(role.discord_role_id):
                raise HTTPException(status_code=400, detail={"code": "membership_role_configuration_missing"})
            if req.role_granted_id is not None and req.role_granted_id != role.id:
                raise HTTPException(status_code=400, detail="El rol de membresía debe corresponder al tipo seleccionado.")
        else:
            # Legacy callers may specify logical IDs directly. Validate them before
            # changing a renewal, instead of letting FK failures escape as HTTP 500.
            for role_id in (req.role_granted_id, req.special_role_id):
                if role_id is not None and await session.get(Role, role_id) is None:
                    raise HTTPException(status_code=404, detail="Rol no encontrado.")
            if req.server_id is not None:
                if not 0 < req.server_id < 2 ** 31:
                    raise HTTPException(status_code=400, detail="El ID de servidor RCON está fuera del rango admitido.")
                if await session.get(RconServer, req.server_id) is None:
                    raise HTTPException(status_code=404, detail="Servidor RCON no encontrado.")

        if req.days is None:
            if m_type is not None:
                days_to_add = m_type.default_days
            else:
                config_key = f"ROLE_DAYS_{norm_type}"
                config_days = (await session.exec(select(BotConfig).where(BotConfig.config_key == config_key))).first()
                try:
                    days_to_add = int(config_days.config_value) if config_days else 30
                except ValueError:
                    raise HTTPException(status_code=400, detail="La configuración de días de esta membresía no es válida.") from None
        else:
            if req.days < 0:
                raise HTTPException(status_code=400, detail="Los días de membresía deben ser 0 (permanente) o un número positivo.")
            days_to_add = req.days
        if discord_source and not 0 <= days_to_add <= 3652:
            raise HTTPException(status_code=400, detail="Warcon admite una vigencia de hasta diez años, o 0 días para una membresía permanente.")

        # Check quota if it's a new membership or one that's inactive
        max_quota = m_type.max_quota if m_type else None

        quota_now = datetime.now(timezone.utc)
        if max_quota is not None:
            usage_stmt = select(func.count(func.distinct(Membership.steam_id))).where(
                func.upper(Membership.membership_type) == norm_type,
                or_(Membership.is_active == True, Membership.is_scheduled == True),
                or_(Membership.end_time == None, Membership.end_time > quota_now),
            )
            current_usage = (await session.exec(usage_stmt)).one()
            
            # If player already has this membership active, it doesn't count as a new slot
            existing_active = (await session.exec(
                select(Membership).where(
                    Membership.steam_id == req.steam_id,
                    func.upper(Membership.membership_type) == norm_type,
                    Membership.is_active == True,
                    or_(Membership.end_time == None, Membership.end_time > quota_now),
                )
            )).first()
            
            if not existing_active and current_usage >= max_quota:
                raise HTTPException(status_code=400, detail=f"No hay cupos disponibles para la membresía tipo {norm_type}. Límite de {max_quota} alcanzado.")

        # Determine server_id scope
        server_id = req.server_id if req.server_id is not None else (m_type.server_id if m_type else None)

        await MembershipsService._require_no_pending_removal(req.steam_id, session)

        start_date = datetime.now(timezone.utc)
        end_date = MembershipsService._add_days(start_date, days_to_add) if days_to_add > 0 else None

        # Check for existing active membership
        existing_membership = (await session.exec(
            select(Membership).where(
                Membership.steam_id == req.steam_id,
                func.upper(Membership.membership_type) == norm_type,
                Membership.is_active == True
            )
        )).first()

        if existing_membership:
            if existing_membership.end_time:
                m_end = existing_membership.end_time
                if m_end.tzinfo is None:
                    m_end = m_end.replace(tzinfo=timezone.utc)
                if m_end > start_date:
                    # Still active, accumulate remaining time to the new membership
                    end_date = MembershipsService._add_days(m_end, days_to_add) if days_to_add > 0 else None
            elif discord_source:
                # Renewing a permanent membership must not shorten its existing benefit.
                end_date = None
                    
        if discord_source and end_date and end_date > start_date + timedelta(days=3652.5):
            raise HTTPException(status_code=400, detail="La vigencia acumulada supera el límite de diez años de Warcon.")
        if discord_source:
            other_active = select(Membership.end_time).where(
                Membership.steam_id == req.steam_id, Membership.is_active == True,
                Membership.server_id == None,
                or_(Membership.end_time == None, Membership.end_time > start_date),
            )
            if existing_membership:
                other_active = other_active.where(Membership.id != existing_membership.id)
            effective_expiry = MembershipsService._effective_slot_expiry([
                end_date, *(await session.exec(other_active)).all(),
            ])
            if effective_expiry and effective_expiry > start_date + timedelta(days=3652.5):
                raise HTTPException(status_code=400, detail="La vigencia del slot reservado supera el límite de diez años de Warcon.")

        # Resolve VIP role from m_type or direct req.role_granted_id
        vip_role_id = req.role_granted_id or (m_type.role_id if m_type else None)
        if not vip_role_id:
            fallback_role = (await session.exec(select(Role).where(func.upper(Role.code) == norm_type))).first()
            if fallback_role:
                vip_role_id = fallback_role.id

        # Determine attached special role
        attached_special_role_id = req.special_role_id
        if discord_source and req.guild_id and req.special_role and not attached_special_role_id:
            # Discord sends a selected role ID. Its guild binding is the only authority.
            special_binding = (await session.exec(select(RoleDiscordBinding).where(
                RoleDiscordBinding.guild_id == req.guild_id,
                RoleDiscordBinding.discord_role_id == req.special_role,
            ))).first()
            if not special_binding:
                raise HTTPException(status_code=409, detail="El rol especial seleccionado no está configurado en este servidor de Discord.")
            attached_special_role_id = special_binding.role_id
        if not attached_special_role_id and req.special_role:
            role_identifier = req.special_role.strip()
            if role_identifier.isascii() and role_identifier.isdigit() and len(role_identifier) < 10:
                sr_obj = await session.get(Role, int(role_identifier))
                if sr_obj:
                    attached_special_role_id = sr_obj.id
            if not attached_special_role_id:
                norm_sr_code = role_identifier.upper().replace(" ", "_")
                sr_obj = (await session.exec(select(Role).where(
                    or_(
                        Role.name == role_identifier,
                        Role.discord_role_id == role_identifier,
                        Role.code == role_identifier,
                        Role.code == norm_sr_code,
                        func.upper(Role.name) == role_identifier.upper()
                    )
                ))).first()
                if sr_obj:
                    attached_special_role_id = sr_obj.id
                else:
                    new_sr = Role(
                        code=role_identifier.upper().replace(" ", "_"),
                        name=role_identifier,
                        discord_role_id=role_identifier,
                        role_type="SPECIAL"
                    )
                    session.add(new_sr)
                    # flush (not commit) — keeps new Role inside the current transaction
                    # so that the subsequent Membership insert is atomic with it.
                    await session.flush()
                    attached_special_role_id = new_sr.id
        elif not attached_special_role_id and existing_membership and existing_membership.special_role_id:
            attached_special_role_id = existing_membership.special_role_id

        if discord_source and attached_special_role_id:
            special = await session.get(Role, attached_special_role_id)
            if not special or (not req.guild_id and not MembershipsService._valid_discord_id(special.discord_role_id)):
                raise HTTPException(status_code=400, detail="El rol especial no tiene un rol de Discord válido configurado.")
        if discord_source and req.guild_id:
            await MembershipRolesService.resolve_roles(
                req.guild_id, [role_id for role_id in (vip_role_id, attached_special_role_id) if role_id], session
            )
        if existing_membership:
            # Validate the guild's complete delivery before changing existing benefits.
            await MembershipsService._deactivate_membership(existing_membership, session)
            existing_membership.end_time = start_date
            session.add(existing_membership)

        membership = Membership(
            steam_id=req.steam_id,
            membership_type=m_type.code if discord_source else req.membership_type,
            start_time=start_date,
            end_time=end_date,
            is_active=True,
            discord_guild_id=req.guild_id if discord_source else None,
            is_booster=req.is_booster or False,
            role_granted_id=vip_role_id,
            special_role_id=attached_special_role_id,
            server_id=server_id,
            payment_source=req.payment_source or "MANUAL",
            creation_operation_id=req.operation_id if discord_source else None,
            creation_request_hash=request_hash if discord_source else None,
        )
        
        # Link VIP role to player_roles
        if membership.role_granted_id:
            vip_pr = (await session.exec(select(PlayerRole).where(
                PlayerRole.steam_id == req.steam_id,
                PlayerRole.role_id == membership.role_granted_id
            ))).first()
            if not vip_pr:
                session.add(PlayerRole(steam_id=req.steam_id, role_id=membership.role_granted_id))

        # Link special badge role to player_roles
        if membership.special_role_id:
            sp_pr = (await session.exec(select(PlayerRole).where(
                PlayerRole.steam_id == req.steam_id,
                PlayerRole.role_id == membership.special_role_id
            ))).first()
            if not sp_pr:
                session.add(PlayerRole(steam_id=req.steam_id, role_id=membership.special_role_id))
                
        session.add(membership)
        await session.commit()
        if discord_source:
            await session.refresh(membership)
            return await MembershipsService._deliver_discord_membership(membership, player, session, guild_id=req.guild_id)
        return {"ok": True, "message": "Membership added"}

    @staticmethod
    def _add_days(base: datetime, days: int) -> datetime:
        """Keep date overflow a validation error, before changing saved benefits."""
        try:
            return base + timedelta(days=days)
        except OverflowError:
            raise HTTPException(status_code=400, detail="La vigencia supera el rango de fechas admitido.") from None

    @staticmethod
    def _valid_discord_id(role_id: Optional[str]) -> bool:
        return bool(isinstance(role_id, str) and role_id and len(role_id) <= 20 and role_id.isascii() and role_id.isdigit()
                    and role_id[0] != "0" and int(role_id) < 2 ** 64)

    @staticmethod
    def _effective_slot_expiry(expiries: List[Optional[datetime]]) -> Optional[datetime]:
        if not expiries or any(expiry is None for expiry in expiries):
            return None
        return max(expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry for expiry in expiries)

    @staticmethod
    async def _deliver_discord_membership(
        membership: Membership, player: Player, session: AsyncSession, replayed: bool = False, guild_id: Optional[str] = None
    ) -> AddMembershipResponse:
        """Deliver this saved membership only. A retry never creates or extends it again."""
        # Creation commits before remote delivery. Reacquire the same player lock
        # so a later renewal cannot overtake this Warcon write with a newer expiry.
        player = (await session.exec(select(Player).where(
            Player.steam_id == membership.steam_id
        ).with_for_update().execution_options(populate_existing=True))).first()
        if not player:
            raise HTTPException(status_code=409, detail="El jugador de esta membresía ya no está registrado.")
        await session.refresh(membership)
        await MembershipsService._require_no_pending_removal(membership.steam_id, session)
        await MembershipsService._require_no_pending_renewal_delivery(membership.steam_id, session)
        if not MembershipsService._valid_discord_id(player.discord_id):
            raise HTTPException(status_code=409, detail="El jugador ya no tiene una cuenta de Discord válida vinculada.")
        now = datetime.now(timezone.utc)
        end_time = membership.end_time
        if end_time and end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        if not membership.is_active or (end_time and end_time <= now):
            raise HTTPException(status_code=409, detail="La membresía de esta operación ya no está vigente.")
        # Existing benefits can still be delivered when their catalog type stops
        # accepting new memberships. Warcon notes use its current human name.
        membership_type = (await session.exec(select(MembershipType).where(
            func.upper(MembershipType.code) == membership.membership_type.strip().upper()
        ))).first()
        if not membership_type:
            raise HTTPException(status_code=409, detail="El tipo de esta membresía ya no está registrado en nuestro sistema.")
        if guild_id:
            if not membership.role_granted_id:
                raise HTTPException(status_code=409, detail={"code": "membership_type_role_missing"})
            role_ids = await MembershipRolesService.resolve_roles(
                guild_id, [role_id for role_id in (membership.role_granted_id, membership.special_role_id) if role_id], session, lock=False
            )
        else:
            role_ids = []
            for role_id in (membership.role_granted_id, membership.special_role_id):
                role = await session.get(Role, role_id) if role_id else None
                if role_id == membership.role_granted_id and (not role or not MembershipsService._valid_discord_id(role.discord_role_id)):
                    raise HTTPException(status_code=409, detail="El rol de Discord de esta membresía ya no está configurado.")
                if role and MembershipsService._valid_discord_id(role.discord_role_id) and role.discord_role_id not in role_ids:
                    role_ids.append(role.discord_role_id)
        # One game slot represents all current global memberships. A shorter new
        # membership must never replace the expiry of a longer or permanent benefit.
        active_expiries = (await session.exec(select(Membership.end_time).where(
            Membership.steam_id == membership.steam_id,
            or_(Membership.is_active == True, Membership.is_scheduled == True),
            Membership.server_id == None,
            or_(Membership.end_time == None, Membership.end_time > now),
        ))).all()
        slot_expiry = MembershipsService._effective_slot_expiry(active_expiries)
        warcon = await WarconClient().upsert_reserved_slot(
            membership.steam_id, membership.id, membership_type.name, slot_expiry
        )
        membership.rcon_sync_status = warcon.status
        session.add(membership)
        await session.commit()
        await session.refresh(membership)
        return AddMembershipResponse(
            ok=True,
            message="Membership already registered" if replayed else "Membership added",
            membership=CreatedMembershipItem(
                id=membership.id, steam_id=membership.steam_id, type=membership.membership_type, type_name=membership_type.name,
                start_date=membership.start_time.replace(tzinfo=timezone.utc) if membership.start_time.tzinfo is None else membership.start_time,
                end_date=end_time, is_booster=membership.is_booster,
                server_id=membership.server_id,
            ),
            discord=MembershipDiscordDelivery(user_id=player.discord_id, role_ids=role_ids, guild_id=guild_id),
            warcon=warcon,
            replayed=replayed,
        )

    @staticmethod
    async def _deactivate_membership(m: Membership, session: AsyncSession, revoke_special_role: bool = False) -> None:
        """
        Desactiva una membresía (is_active = False).
        - Si la membresía tiene un role_granted_id asignado (VIP), verifica si el jugador
          tiene otra membresía activa que otorgue ese mismo role_id.
          Si no tiene otra, elimina ese PlayerRole (VIP).
        - Por regla de negocio, los roles con role_type in ('SPECIAL', 'SYSTEM') (ej. Fundador, Staff)
          son permanentes en la cuenta del jugador y NO se revocan ante expiración de suscripción.
          Solo se revocan si revoke_special_role=True (reembolsos o disputas en Tebex).
        """
        m.is_active = False
        session.add(m)

        # 1. Handle VIP role revocation from player_roles
        vip_role_id = m.role_granted_id
        if not vip_role_id:
            m_type = (await session.exec(
                select(MembershipType).where(func.upper(MembershipType.code) == m.membership_type.upper())
            )).first()
            vip_role_id = m_type.role_id if m_type else None

        if vip_role_id:
            # Check if any OTHER active membership for this player grants the same role_id
            other_active_types = (await session.exec(
                select(Membership.id)
                .outerjoin(MembershipType, func.upper(Membership.membership_type) == func.upper(MembershipType.code))
                .where(
                    Membership.steam_id == m.steam_id,
                    Membership.is_active == True,
                    Membership.id != m.id,
                    or_(
                        Membership.role_granted_id == vip_role_id,
                        MembershipType.role_id == vip_role_id
                    )
                )
            )).first()

            if not other_active_types:
                target_role = await session.get(Role, vip_role_id)
                if target_role and target_role.role_type == "VIP":
                    pr = (await session.exec(select(PlayerRole).where(
                        PlayerRole.steam_id == m.steam_id,
                        PlayerRole.role_id == vip_role_id
                    ))).first()
                    if pr:
                        await session.delete(pr)

        # 2. Handle special badge role revocation (only if explicit dispute/refund)
        if revoke_special_role and m.special_role_id:
            other_active = (await session.exec(select(Membership).where(
                Membership.steam_id == m.steam_id,
                Membership.special_role_id == m.special_role_id,
                Membership.is_active == True,
                Membership.id != m.id
            ))).first()
            if not other_active:
                pr = (await session.exec(select(PlayerRole).where(
                    PlayerRole.steam_id == m.steam_id,
                    PlayerRole.role_id == m.special_role_id
                ))).first()
                if pr:
                    await session.delete(pr)

    @staticmethod
    async def edit_membership(membership_id: int, req: EditMembershipRequest, session: AsyncSession) -> Dict[str, Any]:
        membership = await session.get(Membership, membership_id)
        if not membership:
            raise HTTPException(status_code=404, detail="Membership not found")
        await session.exec(select(Player).where(
            Player.steam_id == membership.steam_id,
        ).with_for_update())
        await session.refresh(membership)
        await MembershipsService._require_no_pending_removal(membership.steam_id, session)
        await MembershipsService._require_no_pending_renewal_delivery(membership.steam_id, session)
        await MembershipsService._require_no_scheduled_renewal(membership.steam_id, session)

        if req.server_id is not None and await session.get(RconServer, req.server_id) is None:
            raise HTTPException(status_code=404, detail="Servidor RCON no encontrado.")
        # Calculate every requested date before mutating the membership or roles.
        now_utc = datetime.now(timezone.utc)
        m_type = None
        norm_type = req.membership_type.strip().upper() if req.membership_type is not None else None
        if norm_type is not None:
            m_type = (await session.exec(select(MembershipType).where(func.upper(MembershipType.code) == norm_type))).first()
        new_end_time = membership.end_time
        date_active = membership.is_active
        start_base = membership.start_time or now_utc
        if start_base.tzinfo is None:
            start_base = start_base.replace(tzinfo=timezone.utc)
        if norm_type is not None and req.days is None:
            if m_type is not None:
                type_days = m_type.default_days
            else:
                config_key = f"ROLE_DAYS_{norm_type}"
                config_days = (await session.exec(select(BotConfig).where(BotConfig.config_key == config_key))).first()
                type_days = 30
                if config_days and config_days.config_value.isascii() and config_days.config_value.isdigit():
                    try:
                        type_days = int(config_days.config_value)
                    except ValueError:
                        raise HTTPException(status_code=400, detail="La configuración de días de esta membresía no es válida.") from None
            new_end_time = (None if type_days == 0 or norm_type == "VIP_PERMANENTE"
                            else MembershipsService._add_days(start_base, type_days))
            if req.is_active is None:
                date_active = new_end_time is None or new_end_time > now_utc
        if req.days is not None:
            if req.days < 0:
                raise HTTPException(status_code=400, detail="Los días de membresía deben ser 0 (permanente) o un número positivo.")
            new_end_time = MembershipsService._add_days(start_base, req.days) if req.days else None
            if req.is_active is None:
                date_active = new_end_time is None or new_end_time > now_utc
        if req.add_days is not None:
            if req.add_days <= 0:
                raise HTTPException(status_code=400, detail="La cantidad de días extra a añadir (add_days) debe ser mayor a 0.")
            if new_end_time is not None:
                base = new_end_time.replace(tzinfo=timezone.utc) if new_end_time.tzinfo is None else new_end_time
                new_end_time = MembershipsService._add_days(max(base, now_utc), req.add_days)
            if req.is_active is None and (new_end_time is None or new_end_time > now_utc):
                date_active = True

        if req.membership_type is not None:
            if m_type and m_type.role_id and membership.role_granted_id != m_type.role_id:
                # Reuse the entitlement checks for the old VIP role. Special
                # badges remain attached according to the existing policy.
                await MembershipsService._deactivate_membership(membership, session)
                membership.role_granted_id = m_type.role_id
            membership.membership_type = req.membership_type
        membership.end_time = new_end_time
        desired_active = req.is_active if req.is_active is not None else date_active
        if not desired_active:
            await MembershipsService._deactivate_membership(membership, session)
        else:
            membership.is_active = True
            for role_id in dict.fromkeys((membership.role_granted_id, membership.special_role_id)):
                if role_id is None:
                    continue
                assigned = await session.get(PlayerRole, (membership.steam_id, role_id))
                if not assigned:
                    session.add(PlayerRole(steam_id=membership.steam_id, role_id=role_id))

        if req.is_booster is not None:
            membership.is_booster = req.is_booster

        if "server_id" in req.model_fields_set:
            membership.server_id = req.server_id
                        
        session.add(membership)
        await session.commit()
        return {"ok": True, "message": "Membership updated"}

    @staticmethod
    async def compensate_memberships(days: int, session: AsyncSession) -> Dict[str, Any]:
        if days <= 0:
            raise HTTPException(status_code=400, detail="La cantidad de días a compensar debe ser mayor a 0.")

        stmt = select(Membership).where(Membership.is_active == True, Membership.end_time != None)
        active_memberships = (await session.exec(stmt)).all()
        
        # A scheduled period starts at the old expiry; changing only that expiry
        # would create an overlap or a gap. Reject the batch before any mutation.
        for steam_id in sorted({m.steam_id for m in active_memberships}):
            await session.exec(select(Player).where(Player.steam_id == steam_id).with_for_update())
            await MembershipsService._require_no_pending_renewal_delivery(steam_id, session)
            await MembershipsService._require_no_scheduled_renewal(steam_id, session)

        # Validate the complete batch before changing any member's benefits.
        updates = [(m, MembershipsService._add_days(m.end_time, days))
                   for m in active_memberships if m.end_time is not None]
        for membership, end_time in updates:
            membership.end_time = end_time
            session.add(membership)
        count = len(updates)
            
        await session.commit()
        if count > 0:
            try:
                await MembershipsService.sync_memberships_logic(session)
            except Exception as e:
                logger.warning(f"Error en sincronización tras compensación masiva: {e}")
        return {"ok": True, "message": f"Compensated {count} memberships with {days} days."}

    @staticmethod
    async def delete_membership(membership_id: int, session: AsyncSession) -> Dict[str, Any]:
        membership = await session.get(Membership, membership_id)
        if not membership:
            raise HTTPException(status_code=404, detail="Membership not found")
            
        await session.exec(select(Player).where(Player.steam_id == membership.steam_id).with_for_update())
        await session.refresh(membership)
        await MembershipsService._require_no_pending_renewal_delivery(membership.steam_id, session)
        await MembershipsService._require_no_scheduled_renewal(membership.steam_id, session)
        history = (await session.exec(select(MembershipRenewalDelivery.id).where(
            or_(MembershipRenewalDelivery.membership_id == membership.id,
                MembershipRenewalDelivery.previous_membership_id == membership.id),
        ).limit(1))).first()
        if history:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_history_preserved"})
        was_active = membership.is_active
        if was_active:
            await MembershipsService._deactivate_membership(membership, session, revoke_special_role=False)
        await session.delete(membership)
        await session.commit()
        if was_active:
            try:
                await MembershipsService.sync_memberships_logic(session)
            except Exception as e:
                logger.warning(f"RCON sync notice after deleting membership #{membership_id}: {e}")
        return {"ok": True, "message": "Membership deleted"}

    @staticmethod
    async def get_paginated_memberships(page: int, limit: int, session: AsyncSession, discord_id: Optional[str] = None,
                                        guild_id: Optional[str] = None) -> Dict[str, Any]:
        if guild_id:
            MembershipRolesService.require_enabled_guild(guild_id)
        target_steam_id = None
        if discord_id:
            player = (await session.exec(select(Player).where(Player.discord_id == discord_id))).first()
            if not player:
                return {
                    "page": page,
                    "limit": limit,
                    "total": 0,
                    "memberships": []
                }
            target_steam_id = player.steam_id

        offset = max(0, (page - 1) * limit)
        statement = select(Membership)
        total_statement = select(func.count(col(Membership.id)))
        if target_steam_id:
            # Personal views show current benefits before newer history; the
            # persisted flag remains authoritative even before expiry maintenance.
            statement = statement.order_by(col(Membership.is_active).desc(), col(Membership.is_scheduled).desc())
            statement = statement.where(Membership.steam_id == target_steam_id)
            total_statement = total_statement.where(Membership.steam_id == target_steam_id)

        statement = statement.order_by(col(Membership.start_time).desc(), col(Membership.id).desc())
        statement = statement.offset(offset).limit(limit)
        memberships = (await session.exec(statement)).all()
        total = (await session.exec(total_statement)).one()
        
        # Enrich only this page; reading historical or roleless records must not
        # mutate delivery state or require a currently configured Discord role.
        steam_ids = {membership.steam_id for membership in memberships}
        players_by_steam: Dict[str, Player] = {}
        if steam_ids:
            players = (await session.exec(select(Player).where(col(Player.steam_id).in_(steam_ids)))).all()
            players_by_steam = {player.steam_id: player for player in players}
        type_codes = {membership.membership_type.strip().upper() for membership in memberships}
        types_by_code: Dict[str, MembershipType] = {}
        if type_codes:
            types = (await session.exec(select(MembershipType).where(func.upper(MembershipType.code).in_(type_codes)))).all()
            types_by_code = {m_type.code.upper(): m_type for m_type in types}

        # Batch load roles to avoid N+1 queries
        role_ids = {
            r_id for m in memberships
            for r_id in (m.special_role_id, m.role_granted_id)
            if r_id is not None
        }
        roles_by_id: Dict[int, Role] = {}
        if role_ids:
            fetched_roles = (await session.exec(select(Role).where(col(Role.id).in_(role_ids)))).all()
            roles_by_id = {r.id: r for r in fetched_roles if r.id is not None}
        discord_roles_by_id = {role_id: role.discord_role_id for role_id, role in roles_by_id.items()}
        if guild_id:
            bindings = (await session.exec(select(RoleDiscordBinding).where(
                RoleDiscordBinding.guild_id == guild_id, col(RoleDiscordBinding.role_id).in_(role_ids),
            ))).all() if role_ids else []
            discord_roles_by_id = {binding.role_id: binding.discord_role_id for binding in bindings}

        results = []
        for m in memberships:
            membership_type = types_by_code.get(m.membership_type.strip().upper())
            player = players_by_steam.get(m.steam_id)
            special_role_name = None
            special_discord_role_id = None
            if m.special_role_id and m.special_role_id in roles_by_id:
                r = roles_by_id[m.special_role_id]
                special_role_name = r.name
                special_discord_role_id = discord_roles_by_id.get(m.special_role_id)

            role_granted_name = None
            role_granted_discord_id = None
            if m.role_granted_id and m.role_granted_id in roles_by_id:
                rg = roles_by_id[m.role_granted_id]
                role_granted_name = rg.name
                role_granted_discord_id = discord_roles_by_id.get(m.role_granted_id)
            
            results.append({
                "id": m.id,
                "steam_id": m.steam_id,
                "type": m.membership_type,
                "type_name": membership_type.name if membership_type else m.membership_type,
                "discord_id": player.discord_id if player else None,
                "is_active": m.is_active,
                "is_scheduled": m.is_scheduled,
                "is_booster": m.is_booster,
                "server_id": m.server_id,
                "start_date": m.start_time.isoformat(),
                "end_date": m.end_time.isoformat() if m.end_time else None,
                "role_granted_id": m.role_granted_id,
                "role_granted_name": role_granted_name,
                "role_granted_discord_id": role_granted_discord_id,
                "special_role": special_role_name,
                "special_role_id": m.special_role_id,
                "special_discord_role_id": special_discord_role_id,
                "rcon_sync_status": m.rcon_sync_status,
            })
        
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "memberships": results
        }

    @staticmethod
    async def sync_memberships_logic(session: AsyncSession) -> Dict[str, Any]:
        from src.modules.v1.services.membership_renewals_service import MembershipRenewalsService
        await MembershipRenewalsService.activate_due(session)
        now = datetime.now(timezone.utc)
        
        # 1. Expire old memberships
        expired_stmt = select(Membership).where(
            Membership.is_active == True,
            Membership.end_time != None,
            col(Membership.end_time) <= now
        ).order_by(col(Membership.id))
        expired = (await session.exec(expired_stmt)).all()
        for m in expired:
            await session.exec(select(Player).where(Player.steam_id == m.steam_id).with_for_update())
            await session.refresh(m)
            if m.is_active and m.end_time and (m.end_time.replace(tzinfo=timezone.utc) if m.end_time.tzinfo is None else m.end_time) <= now:
                await MembershipsService._deactivate_membership(m, session)
                        
        if expired:
            await session.commit()
            
        # 2. Get active steam_ids
        active_stmt = select(Membership.steam_id).where(Membership.is_active == True).distinct()
        active_steam_ids = set((await session.exec(active_stmt)).all())

        # Warcon owns its list and expiry; legacy RCON must not overwrite that list.
        if not ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.WARCON_URL.strip():
            # 3. Sync RCON per-server (respecting server_id scope)
            sync_failed = False
            try:
                active_servers = await RCONManager.get_all_active_servers(session)
                for s_info, client in active_servers:
                    try:
                        if s_info.id is not None:
                            s_vip_stmt = select(Membership.steam_id).where(
                                Membership.is_active == True,
                                or_(Membership.server_id == None, Membership.server_id == s_info.id)
                            ).distinct()
                        else:
                            s_vip_stmt = select(Membership.steam_id).where(
                                Membership.is_active == True,
                                Membership.server_id == None
                            ).distinct()
                        raw_sids = set((await session.exec(s_vip_stmt)).all())
                        server_steam_ids = sorted(list(raw_sids))
                        await client.sync_reserved_slots(server_steam_ids)
                    except Exception as s_err:
                        sync_failed = True
                        logger.warning(f"Failed to sync RCON reserved slots to {s_info.name} ({s_info.base_url}): {s_err}")
            
                if not sync_failed:
                    # Update pending RCON sync status only if all active servers succeeded
                    pending_m_stmt = select(Membership).where(
                        Membership.is_active == True,
                        Membership.rcon_sync_status != "SUCCESS"
                    ).order_by(col(Membership.id))
                    for m in (await session.exec(pending_m_stmt)).all():
                        m.rcon_sync_status = "SUCCESS"
                        session.add(m)
                    await session.commit()
            
            except Exception as e:
                logger.error(f"Failed to sync RCON reserved slots: {e}", exc_info=True)
            
        # 4. Prepare data for Discord Bot Role Sync
        players_stmt = select(Player).where(Player.discord_id != None).order_by(col(Player.steam_id))
        players = (await session.exec(players_stmt)).all()
        
        # Batch query all active memberships by steam_id to avoid N+1 queries
        active_m_stmt = select(Membership.steam_id, Membership.membership_type).where(Membership.is_active == True).order_by(col(Membership.id))
        all_active_m = (await session.exec(active_m_stmt)).all()
        m_types_by_steam: Dict[str, List[str]] = {}
        for sid, mtype in all_active_m:
            m_types_by_steam.setdefault(sid, []).append(mtype)

        # Batch query all player roles by steam_id (roles assigned to player that are Discord-managed)
        pr_stmt = (
            select(PlayerRole.steam_id, Role.discord_role_id)
            .join(Role, col(PlayerRole.role_id) == col(Role.id))
            .where(
                Role.discord_role_id != None
            )
            .order_by(col(PlayerRole.steam_id), col(PlayerRole.role_id))
        )
        all_pr = (await session.exec(pr_stmt)).all()
        roles_by_steam: Dict[str, List[int]] = {}
        for sid, dr_id in all_pr:
            if dr_id and str(dr_id).isdigit():
                roles_by_steam.setdefault(sid, []).append(int(dr_id))

        discord_sync_data = []
        for p in players:
            discord_sync_data.append({
                "discord_id": p.discord_id,
                "active_memberships": m_types_by_steam.get(p.steam_id, []),
                "special_roles": roles_by_steam.get(p.steam_id, [])
            })
            
        all_roles = (await session.exec(select(Role).order_by(Role.id))).all()
        roles_by_id = {r.id: r for r in all_roles if r.id is not None}
        role_maps: Dict[str, int] = {}
        for r in all_roles:
            if r.role_type == "VIP" and r.discord_role_id and str(r.discord_role_id).isdigit():
                dr_val = int(r.discord_role_id)
                role_maps[r.code] = dr_val
                role_maps[r.code.upper()] = dr_val
                role_maps[r.name] = dr_val
                role_maps[r.code.replace("_", " ")] = dr_val

        all_types = (await session.exec(select(MembershipType).order_by(MembershipType.id))).all()
        for mt in all_types:
            dr_id = None
            if mt.role_id and mt.role_id in roles_by_id:
                dr_id = roles_by_id[mt.role_id].discord_role_id
            if dr_id and str(dr_id).isdigit():
                dr_val = int(dr_id)
                role_maps[mt.code] = dr_val
                role_maps[mt.code.upper()] = dr_val
                role_maps[mt.name] = dr_val
                role_maps[mt.code.replace("_", " ")] = dr_val

        managed_special_roles = [
            int(r.discord_role_id)
            for r in all_roles
            if r.role_type != "VIP" and r.discord_role_id and str(r.discord_role_id).isdigit()
        ]
            
        return {
            "sync_data": discord_sync_data, 
            "role_maps": role_maps,
            "managed_special_roles": managed_special_roles,
            "expired_count": len(expired),
            "active_rcon_slots": len(active_steam_ids)
        }

    @staticmethod
    async def get_rcon_sync_status(session: AsyncSession) -> Dict[str, Any]:
        active_stmt = select(Membership.steam_id).where(Membership.is_active == True).distinct()
        active_steam_ids = set((await session.exec(active_stmt)).all())
        
        server_info, client = await RCONManager.get_default_server(session)
        try:
            current_slots_resp = await client.get_reserved_slots()
            current_slots = set(current_slots_resp.reservedSlots or [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch from RCON ({server_info.name}): {e}")
        
        synced = sorted(list(active_steam_ids.intersection(current_slots)))
        pending_add = sorted(list(active_steam_ids - current_slots))
        pending_remove = sorted(list(current_slots - active_steam_ids))
        
        return {
            "server": server_info.name,
            "synced": synced,
            "pending_add": pending_add,
            "pending_remove": pending_remove
        }
