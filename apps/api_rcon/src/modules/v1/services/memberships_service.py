import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.rcon import RCONManager
from src.connections.databases.db import (
    BotConfig,
    Membership,
    MembershipType,
    Player,
    PlayerRole,
    Role,
)
from src.modules.v1.schemas.dtos import (
    AddMembershipRequest,
    EditMembershipRequest,
)

logger = logging.getLogger("wardogs.memberships")

class MembershipsService:
    @staticmethod
    async def add_membership(req: AddMembershipRequest, session: AsyncSession) -> dict[str, Any]:
        player = (await session.exec(select(Player).where(Player.steam_id == req.steam_id).with_for_update())).first()
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        
        norm_type = req.membership_type.strip().upper()
        m_type = (await session.exec(select(MembershipType).where(func.upper(MembershipType.code) == norm_type))).first()

        if req.days is None:
            if m_type is not None:
                days_to_add = m_type.default_days
            else:
                config_key = f"ROLE_DAYS_{norm_type}"
                config_days = (await session.exec(select(BotConfig).where(BotConfig.config_key == config_key))).first()
                days_to_add = int(config_days.config_value) if config_days else 30
        else:
            if req.days < 0:
                raise HTTPException(status_code=400, detail="Los días de membresía deben ser 0 (permanente) o un número positivo.")
            days_to_add = req.days

        # Check quota if it's a new membership or one that's inactive
        max_quota = m_type.max_quota if m_type else None

        if max_quota is not None:
            usage_stmt = select(func.count(col(Membership.id))).where(func.upper(Membership.membership_type) == norm_type, Membership.is_active == True)
            current_usage = (await session.exec(usage_stmt)).one()
            
            # If player already has this membership active, it doesn't count as a new slot
            existing_active = (await session.exec(
                select(Membership).where(
                    Membership.steam_id == req.steam_id,
                    func.upper(Membership.membership_type) == norm_type,
                    Membership.is_active == True
                )
            )).first()
            
            if not existing_active and current_usage >= max_quota:
                raise HTTPException(status_code=400, detail=f"No hay cupos disponibles para la membresía tipo {norm_type}. Límite de {max_quota} alcanzado.")

        # Determine server_id scope
        server_id = req.server_id if req.server_id is not None else (m_type.server_id if m_type else None)

        start_date = datetime.now(UTC)
        end_date = start_date + timedelta(days=days_to_add) if days_to_add > 0 else None

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
                    m_end = m_end.replace(tzinfo=UTC)
                if m_end > start_date:
                    # Still active, accumulate remaining time to the new membership
                    remaining_time = m_end - start_date
                    end_date = start_date + remaining_time + timedelta(days=days_to_add) if days_to_add > 0 else None
                    
            # Expire the old membership to keep history intact
            await MembershipsService._deactivate_membership(existing_membership, session)
            existing_membership.end_time = start_date # Mark it as ended now
            session.add(existing_membership)
        
        # Resolve VIP role from m_type or direct req.role_granted_id
        vip_role_id = req.role_granted_id or (m_type.role_id if m_type else None)
        if not vip_role_id:
            fallback_role = (await session.exec(select(Role).where(func.upper(Role.code) == norm_type))).first()
            if fallback_role:
                vip_role_id = fallback_role.id

        # Determine attached special role
        attached_special_role_id = req.special_role_id
        if not attached_special_role_id and req.special_role:
            role_identifier = req.special_role.strip()
            if role_identifier.isdigit() and len(role_identifier) < 10:
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

        membership = Membership(
            steam_id=req.steam_id,
            membership_type=req.membership_type,
            start_time=start_date,
            end_time=end_date,
            is_active=True,
            is_booster=req.is_booster or False,
            role_granted_id=vip_role_id,
            special_role_id=attached_special_role_id,
            server_id=server_id,
            payment_source=req.payment_source or "MANUAL"
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
        return {"ok": True, "message": "Membership added"}

    @staticmethod
    async def _deactivate_membership(m: Membership, session: AsyncSession, revoke_special_role: bool = False) -> None:
        """
        Desactiva una membresía (is_active = False).
        - Si la membresía tiene un role_granted_id asignado (VIP), verifica si el jugador
          tiene otra membresía activa que otorgue ese mismo role_id.
          Si no tiene otra, elimina ese PlayerRole (VIP).
        - Por regla de negocio, los roles con role_type in ('SPECIAL', 'SYSTEM') (ej. Fundador, Staff)
          son permanentes en la cuenta del jugador y NO se revocan ante expiración de suscripción.
          Solo se revocan si revoke_special_role=True (reembolsos o disputas).
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
    async def edit_membership(membership_id: int, req: EditMembershipRequest, session: AsyncSession) -> dict[str, Any]:
        membership = await session.get(Membership, membership_id)
        if not membership:
            raise HTTPException(status_code=404, detail="Membership not found")
            
        if req.membership_type is not None:
            norm_type = req.membership_type.strip().upper()
            membership.membership_type = req.membership_type
            
            # Synchronize role_granted_id and player_roles with new membership type
            m_type = (await session.exec(select(MembershipType).where(func.upper(MembershipType.code) == norm_type))).first()
            if m_type and m_type.role_id:
                old_role_id = membership.role_granted_id
                if old_role_id != m_type.role_id:
                    membership.role_granted_id = m_type.role_id
                    if membership.is_active:
                        if old_role_id:
                            other_active = (await session.exec(
                                select(Membership.id).where(
                                    Membership.steam_id == membership.steam_id,
                                    Membership.is_active == True,
                                    Membership.id != membership.id,
                                    Membership.role_granted_id == old_role_id
                                )
                            )).first()
                            if not other_active:
                                old_r = await session.get(Role, old_role_id)
                                if old_r and old_r.role_type == "VIP":
                                    old_pr = (await session.exec(select(PlayerRole).where(
                                        PlayerRole.steam_id == membership.steam_id,
                                        PlayerRole.role_id == old_role_id
                                    ))).first()
                                    if old_pr:
                                        await session.delete(old_pr)
                        new_pr = (await session.exec(select(PlayerRole).where(
                            PlayerRole.steam_id == membership.steam_id,
                            PlayerRole.role_id == m_type.role_id
                        ))).first()
                        if not new_pr:
                            session.add(PlayerRole(steam_id=membership.steam_id, role_id=m_type.role_id))
            
            # Si se edita el tipo y no se pasaron días explícitos, ajustar la fecha de acuerdo al tipo (achicarse o agrandarse)
            if req.days is None:
                if m_type is not None:
                    type_days = m_type.default_days
                else:
                    config_key = f"ROLE_DAYS_{norm_type}"
                    config_days = (await session.exec(select(BotConfig).where(BotConfig.config_key == config_key))).first()
                    if config_days and config_days.config_value.isdigit():
                        type_days = int(config_days.config_value)
                    else:
                        type_days = 30
                
                start_base = membership.start_time or datetime.now(UTC)
                if start_base.tzinfo is None:
                    start_base = start_base.replace(tzinfo=UTC)
                
                if type_days == 0 or norm_type == "VIP_PERMANENTE":
                    membership.end_time = None
                    if req.is_active is None:
                        membership.is_active = True
                else:
                    membership.end_time = start_base + timedelta(days=type_days)
                    if req.is_active is None:
                        now_utc = datetime.now(UTC)
                        end_dt = membership.end_time
                        if end_dt is not None and end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=UTC)
                        membership.is_active = end_dt is not None and end_dt > now_utc
            
        if req.days is not None:
            if req.days < 0:
                raise HTTPException(status_code=400, detail="Los días de membresía deben ser 0 (permanente) o un número positivo.")
            if req.days == 0:
                membership.end_time = None
                if req.is_active is None:
                    membership.is_active = True
            else:
                start_base = membership.start_time or datetime.now(UTC)
                membership.end_time = start_base + timedelta(days=req.days)
                if req.is_active is None:
                    now_utc = datetime.now(UTC)
                    end_dt = membership.end_time
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=UTC)
                    membership.is_active = end_dt > now_utc
                
        if req.add_days is not None:
            if req.add_days <= 0:
                raise HTTPException(status_code=400, detail="La cantidad de días extra a añadir (add_days) debe ser mayor a 0.")
            now_utc = datetime.now(UTC)
            base_time = membership.end_time
            if base_time is not None:
                if base_time.tzinfo is None:
                    base_time = base_time.replace(tzinfo=UTC)
                effective_base = max(base_time, now_utc)
                membership.end_time = effective_base + timedelta(days=req.add_days)
            else:
                pass

            if req.is_active is None:
                end_dt = membership.end_time
                if end_dt is not None and end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=UTC)
                if end_dt is None or end_dt > now_utc:
                    membership.is_active = True
                    if membership.role_granted_id:
                        vip_pr = (await session.exec(select(PlayerRole).where(
                            PlayerRole.steam_id == membership.steam_id,
                            PlayerRole.role_id == membership.role_granted_id
                        ))).first()
                        if not vip_pr:
                            session.add(PlayerRole(steam_id=membership.steam_id, role_id=membership.role_granted_id))
                    if membership.special_role_id:
                        sp_pr = (await session.exec(select(PlayerRole).where(
                            PlayerRole.steam_id == membership.steam_id,
                            PlayerRole.role_id == membership.special_role_id
                        ))).first()
                        if not sp_pr:
                            session.add(PlayerRole(steam_id=membership.steam_id, role_id=membership.special_role_id))
                
        if req.is_active is not None:
            if not req.is_active:
                await MembershipsService._deactivate_membership(membership, session)
            else:
                membership.is_active = True
                if membership.role_granted_id:
                    vip_pr = (await session.exec(select(PlayerRole).where(
                        PlayerRole.steam_id == membership.steam_id,
                        PlayerRole.role_id == membership.role_granted_id
                    ))).first()
                    if not vip_pr:
                        session.add(PlayerRole(steam_id=membership.steam_id, role_id=membership.role_granted_id))
                if membership.special_role_id:
                    sp_pr = (await session.exec(select(PlayerRole).where(
                        PlayerRole.steam_id == membership.steam_id,
                        PlayerRole.role_id == membership.special_role_id
                    ))).first()
                    if not sp_pr:
                        session.add(PlayerRole(steam_id=membership.steam_id, role_id=membership.special_role_id))
                session.add(membership)

        if req.is_booster is not None:
            membership.is_booster = req.is_booster

        if "server_id" in req.model_fields_set:
            membership.server_id = req.server_id
                        
        session.add(membership)
        await session.commit()
        return {"ok": True, "message": "Membership updated"}

    @staticmethod
    async def compensate_memberships(days: int, session: AsyncSession) -> dict[str, Any]:
        if days <= 0:
            raise HTTPException(status_code=400, detail="La cantidad de días a compensar debe ser mayor a 0.")

        stmt = select(Membership).where(Membership.is_active == True, Membership.end_time != None)
        active_memberships = (await session.exec(stmt)).all()
        
        count = 0
        for m in active_memberships:
            if m.end_time:
                m.end_time = m.end_time + timedelta(days=days)
                session.add(m)
                count += 1
            
        await session.commit()
        if count > 0:
            try:
                await MembershipsService.sync_memberships_logic(session)
            except Exception as e:
                logger.warning(f"Error en sincronización tras compensación masiva: {e}")
        return {"ok": True, "message": f"Compensated {count} memberships with {days} days."}

    @staticmethod
    async def delete_membership(membership_id: int, session: AsyncSession) -> dict[str, Any]:
        membership = await session.get(Membership, membership_id)
        if not membership:
            raise HTTPException(status_code=404, detail="Membership not found")
            
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
    async def get_paginated_memberships(page: int, limit: int, session: AsyncSession, discord_id: str | None = None) -> dict[str, Any]:
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
        statement = select(Membership).order_by(col(Membership.start_time).desc())
        total_statement = select(func.count(col(Membership.id)))
        if target_steam_id:
            statement = statement.where(Membership.steam_id == target_steam_id)
            total_statement = total_statement.where(Membership.steam_id == target_steam_id)

        statement = statement.offset(offset).limit(limit)
        memberships = (await session.exec(statement)).all()
        total = (await session.exec(total_statement)).one()
        
        # Batch load roles to avoid N+1 queries
        role_ids = {
            r_id for m in memberships
            for r_id in (m.special_role_id, m.role_granted_id)
            if r_id is not None
        }
        roles_by_id: dict[int, Role] = {}
        if role_ids:
            fetched_roles = (await session.exec(select(Role).where(col(Role.id).in_(role_ids)))).all()
            roles_by_id = {r.id: r for r in fetched_roles if r.id is not None}

        results = []
        for m in memberships:
            special_role_name = None
            special_discord_role_id = None
            if m.special_role_id and m.special_role_id in roles_by_id:
                r = roles_by_id[m.special_role_id]
                special_role_name = r.name
                special_discord_role_id = r.discord_role_id

            role_granted_name = None
            role_granted_discord_id = None
            if m.role_granted_id and m.role_granted_id in roles_by_id:
                rg = roles_by_id[m.role_granted_id]
                role_granted_name = rg.name
                role_granted_discord_id = rg.discord_role_id
            
            results.append({
                "id": m.id,
                "steam_id": m.steam_id,
                "type": m.membership_type,
                "is_active": m.is_active,
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
                "rcon_sync_status": "SUCCESS" if m.is_active else "INACTIVE",
            })
        
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "memberships": results
        }

    @staticmethod
    async def sync_memberships_logic(session: AsyncSession) -> dict[str, Any]:
        now = datetime.now(UTC)
        
        # 1. Expire old memberships
        expired_stmt = select(Membership).where(
            Membership.is_active == True,
            Membership.end_time != None,
            col(Membership.end_time) < now
        ).order_by(col(Membership.id))
        expired = (await session.exec(expired_stmt)).all()
        for m in expired:
            await MembershipsService._deactivate_membership(m, session)
                        
        if expired:
            await session.commit()
            
        # 2. Get active steam_ids
        active_stmt = select(Membership.steam_id).where(Membership.is_active == True).distinct()
        active_steam_ids = set((await session.exec(active_stmt)).all())

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
        m_types_by_steam: dict[str, list[str]] = {}
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
        roles_by_steam: dict[str, list[int]] = {}
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
        role_maps: dict[str, int] = {}
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
    async def get_rcon_sync_status(session: AsyncSession) -> dict[str, Any]:
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
    @staticmethod
    async def get_expiring_memberships(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
        now = datetime.now(UTC)
        three_days_from_now = now + timedelta(days=3)
        one_day_from_now = now + timedelta(hours=24)
        
        # We need players with active memberships where end_time is not None, and either:
        # (end_time <= three_days_from_now and not notified_3d)
        # OR
        # (end_time <= one_day_from_now and not notified_24h)
        
        stmt = select(Membership, Player.discord_id).join(Player).where(
            Membership.is_active == True,
            Membership.end_time != None,
            or_(
                (Membership.end_time <= three_days_from_now) & (Membership.notified_3d == False),
                (Membership.end_time <= one_day_from_now) & (Membership.notified_24h == False)
            )
        )
        
        results = await session.execute(stmt)
        
        expiring_3d = []
        expiring_24h = []
        
        for membership, discord_id in results:
            if not discord_id:
                continue
                
            mem_dict = {
                "id": membership.id,
                "steam_id": membership.steam_id,
                "discord_id": discord_id,
                "type": membership.membership_type,
                "end_time": membership.end_time.isoformat() if membership.end_time else None
            }
            
            # Check 24h first because it's more urgent
            if membership.end_time <= one_day_from_now and not membership.notified_24h:
                expiring_24h.append(mem_dict)
            elif membership.end_time <= three_days_from_now and not membership.notified_3d:
                expiring_3d.append(mem_dict)
                
        return {
            "expiring_3d": expiring_3d,
            "expiring_24h": expiring_24h
        }

    @staticmethod
    async def mark_membership_notified(membership_id: int, notification_type: str, session: AsyncSession) -> bool:
        membership = (await session.exec(select(Membership).where(Membership.id == membership_id))).first()
        if not membership:
            return False
            
        if notification_type == "3d":
            membership.notified_3d = True
        elif notification_type == "24h":
            membership.notified_24h = True
            
        session.add(membership)
        await session.commit()
        return True
