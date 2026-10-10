"""Schedule membership periods; Python owns dates/Warcon and the bot delivers roles."""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import (
    Membership, MembershipRenewalDelivery, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding,
)
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.modules.v1.services.memberships_service import MembershipsService
from wardogs_schemas.dtos import (
    CompleteMembershipRenewalRequest, CompleteMembershipRenewalResponse, CreatedMembershipItem,
    MembershipDiscordDelivery, MembershipRenewalDeliveriesResponse, MembershipRenewalRoleDelivery,
    RenewMembershipRequest, RenewMembershipResponse,
)

logger = logging.getLogger("wardogs.memberships")


class MembershipRenewalsService:
    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    async def _player(steam_id: str, session: AsyncSession, skip_locked: bool = False) -> Player | None:
        player = (await session.exec(select(Player).where(
            Player.steam_id == steam_id,
        ).with_for_update(skip_locked=skip_locked).execution_options(populate_existing=True))).first()
        if not player and not skip_locked:
            raise HTTPException(status_code=404, detail="Player not found")
        return player

    @staticmethod
    async def _roles(membership: Membership, guild_id: str, session: AsyncSession) -> list[str]:
        if not membership.role_granted_id:
            raise HTTPException(status_code=409, detail={"code": "membership_type_role_missing"})
        return await MembershipRolesService.resolve_roles(
            guild_id, [role_id for role_id in (membership.role_granted_id, membership.special_role_id) if role_id], session,
        )

    @staticmethod
    async def _vip_roles(membership: Membership, guild_id: str, session: AsyncSession) -> list[str]:
        logical_role = membership.role_granted_id
        if not logical_role:
            membership_type = (await session.exec(select(MembershipType).where(
                func.upper(MembershipType.code) == membership.membership_type.strip().upper(),
            ))).first()
            logical_role = membership_type.role_id if membership_type else None
        role = await session.get(Role, logical_role) if logical_role else None
        if not role or role.role_type != "VIP":
            return []
        return await MembershipRolesService.resolve_roles(guild_id, [role.id], session, lock=False)

    @staticmethod
    async def renew(req: RenewMembershipRequest, session: AsyncSession) -> RenewMembershipResponse:
        MembershipRolesService.require_enabled_guild(req.guild_id)
        player = await MembershipRenewalsService._player(req.steam_id, session)
        request_hash = hashlib.sha256(json.dumps(
            {"operation": "renew", **req.model_dump(exclude={"operation_id"})}, sort_keys=True,
        ).encode()).hexdigest()
        previous_operation = (await session.exec(select(Membership).where(
            Membership.creation_operation_id == req.operation_id,
        ))).first()
        if previous_operation:
            if previous_operation.creation_request_hash != request_hash:
                raise HTTPException(status_code=409, detail={"code": "membership_renewal_operation_conflict"})
            receipt = (await session.exec(select(MembershipRenewalDelivery).where(
                MembershipRenewalDelivery.membership_id == previous_operation.id, MembershipRenewalDelivery.phase == "START",
            ))).first()
            if not receipt or receipt.cancelled:
                raise HTTPException(status_code=409, detail={"code": "membership_renewal_cancelled"})
            return await MembershipRenewalsService._deliver(previous_operation, receipt, player, session, replayed=True)

        await MembershipsService._require_no_pending_removal(req.steam_id, session)
        await MembershipsService._require_no_pending_renewal_delivery(req.steam_id, session)
        if not MembershipsService._valid_discord_id(player.discord_id):
            raise HTTPException(status_code=409, detail="El jugador no tiene una cuenta de Discord válida vinculada.")
        pending = (await session.exec(select(Membership.id).where(
            Membership.steam_id == req.steam_id, Membership.is_scheduled == True,
        ).limit(1))).first()
        if pending:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_already_scheduled"})

        now = datetime.now(timezone.utc)
        current = (await session.exec(select(Membership).where(
            Membership.steam_id == req.steam_id, Membership.is_active == True,
            Membership.start_time <= now, or_(Membership.end_time == None, Membership.end_time > now),
        ).order_by(Membership.id).execution_options(populate_existing=True))).all()
        if not current:
            raise HTTPException(status_code=404, detail={"code": "membership_renewal_not_found"})
        if len(current) != 1 or current[0].server_id is not None:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_ambiguous"})
        previous = current[0]
        if previous.discord_guild_id and previous.discord_guild_id != req.guild_id:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_other_guild"})
        if previous.end_time is None:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_permanent"})
        norm_type = req.membership_type.strip().upper()
        m_type = (await session.exec(select(MembershipType).where(
            func.upper(MembershipType.code) == norm_type,
        ).with_for_update().execution_options(populate_existing=True))).first()
        if not m_type or not m_type.is_active:
            raise HTTPException(status_code=400, detail="Seleccioná un tipo de membresía activo registrado en nuestro sistema.")
        if m_type.server_id is not None:
            raise HTTPException(status_code=400, detail={"code": "membership_renewal_ambiguous"})
        days = m_type.default_days if req.days is None else req.days
        if not 0 <= days <= 3652:
            raise HTTPException(status_code=400, detail={"code": "membership_renewal_invalid_duration"})
        start = MembershipRenewalsService._utc(previous.end_time)
        end = MembershipsService._add_days(start, days) if days > 0 else None
        if end and end > now + timedelta(days=3652.5):
            raise HTTPException(status_code=400, detail={"code": "membership_renewal_limit_exceeded"})
        if m_type.max_quota is not None:
            users = (await session.exec(select(func.count(func.distinct(Membership.steam_id))).where(
                func.upper(Membership.membership_type) == norm_type,
                or_(Membership.is_active == True, Membership.is_scheduled == True),
                or_(Membership.end_time == None, Membership.end_time > now),
                Membership.steam_id != req.steam_id,
            ))).one()
            if users >= m_type.max_quota:
                raise HTTPException(status_code=409, detail={"code": "membership_renewal_quota_exceeded"})
        WarconClient().validate_configuration()
        membership = Membership(
            steam_id=req.steam_id, membership_type=m_type.code, start_time=start, end_time=end,
            is_active=False, is_scheduled=True, discord_guild_id=req.guild_id, is_booster=previous.is_booster,
            role_granted_id=m_type.role_id, special_role_id=previous.special_role_id,
            server_id=None, payment_source="MANUAL", creation_operation_id=req.operation_id,
            creation_request_hash=request_hash,
        )
        # Validate both sides before saving a period that will later change roles.
        new_roles = await MembershipRenewalsService._roles(membership, req.guild_id, session)
        old_roles = await MembershipRenewalsService._vip_roles(previous, req.guild_id, session)
        if previous.discord_guild_id is None:
            previous.discord_guild_id = req.guild_id
            session.add(previous)
        session.add(membership)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_operation_conflict"}) from None
        receipt = MembershipRenewalDelivery(
            membership_id=membership.id, previous_membership_id=previous.id, guild_id=req.guild_id,
            actor_id=req.actor_id, user_id=player.discord_id, available_at=start,
            role_ids_to_add_json=json.dumps(new_roles), role_ids_to_remove_json=json.dumps(old_roles),
        )
        session.add(receipt)
        if end is not None:
            next_vip = await MembershipRenewalsService._vip_roles(membership, req.guild_id, session)
            session.add(MembershipRenewalDelivery(
                membership_id=membership.id, previous_membership_id=previous.id, phase="END",
                guild_id=req.guild_id, actor_id=req.actor_id, user_id=player.discord_id, available_at=end,
                role_ids_to_add_json="[]", role_ids_to_remove_json=json.dumps(next_vip),
            ))
        await session.commit()
        await session.refresh(membership)
        await session.refresh(receipt)
        logger.info("membership_renewal actor_id=%s guild_id=%s steam_id=%s previous_membership_id=%s membership_id=%s",
                    req.actor_id, req.guild_id, req.steam_id, previous.id, membership.id)
        return await MembershipRenewalsService._deliver(membership, receipt, player, session)

    @staticmethod
    async def _deliver(membership: Membership, receipt: MembershipRenewalDelivery, player: Player,
                       session: AsyncSession, replayed: bool = False) -> RenewMembershipResponse:
        player = await MembershipRenewalsService._player(membership.steam_id, session)
        await session.refresh(membership)
        await session.refresh(receipt)
        await MembershipsService._require_no_pending_removal(membership.steam_id, session)
        if receipt.cancelled or (not membership.is_active and not membership.is_scheduled):
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_cancelled"})
        if not MembershipsService._valid_discord_id(player.discord_id) or player.discord_id != receipt.user_id:
            raise HTTPException(status_code=409, detail="El jugador ya no tiene la misma cuenta de Discord vinculada.")
        m_type = (await session.exec(select(MembershipType).where(
            func.upper(MembershipType.code) == membership.membership_type.strip().upper(),
        ))).first()
        if not m_type:
            raise HTTPException(status_code=409, detail="El tipo de esta membresía ya no está registrado en nuestro sistema.")
        await MembershipRenewalsService._roles(membership, receipt.guild_id, session)
        now = datetime.now(timezone.utc)
        expiries = (await session.exec(select(Membership.end_time).where(
            Membership.steam_id == membership.steam_id, Membership.server_id == None,
            or_(Membership.is_active == True, Membership.is_scheduled == True),
            or_(Membership.end_time == None, Membership.end_time > now),
        ))).all()
        warcon = await WarconClient().upsert_reserved_slot(
            membership.steam_id, membership.id, m_type.name, MembershipsService._effective_slot_expiry(expiries),
        )
        membership.rcon_sync_status = warcon.status
        session.add(membership)
        await session.commit()
        return RenewMembershipResponse(
            ok=True, message="Membership renewal already registered" if replayed else "Membership renewal scheduled",
            previous_membership_id=receipt.previous_membership_id,
            membership=CreatedMembershipItem(
                id=membership.id, steam_id=membership.steam_id, type=membership.membership_type, type_name=m_type.name,
                start_date=MembershipRenewalsService._utc(membership.start_time),
                end_date=MembershipRenewalsService._utc(membership.end_time) if membership.end_time else None,
                is_booster=membership.is_booster, server_id=membership.server_id,
            ),
            discord=MembershipDiscordDelivery(user_id=receipt.user_id, guild_id=receipt.guild_id, role_ids=[]),
            warcon=warcon, replayed=replayed,
        )

    @staticmethod
    def _snapshot(value: str) -> list[str]:
        try:
            roles = json.loads(value)
        except (TypeError, ValueError):
            roles = None
        if not isinstance(roles, list) or any(not MembershipsService._valid_discord_id(role) for role in roles):
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_delivery_invalid"})
        return list(dict.fromkeys(roles))

    @staticmethod
    async def activate_due(session: AsyncSession, guild_id: str | None = None, skip_locked: bool = False) -> int:
        """Make due periods current before expiry removes the previous role entitlement."""
        now = datetime.now(timezone.utc)
        statement = select(MembershipRenewalDelivery.id).join(Membership, MembershipRenewalDelivery.membership_id == Membership.id).where(
            MembershipRenewalDelivery.activated == False, MembershipRenewalDelivery.cancelled == False,
            MembershipRenewalDelivery.phase == "START",
            MembershipRenewalDelivery.available_at <= now, Membership.is_scheduled == True,
        ).order_by(MembershipRenewalDelivery.id)
        if guild_id:
            statement = statement.where(MembershipRenewalDelivery.guild_id == guild_id)
        delivery_ids = (await session.exec(statement)).all()
        activated = 0
        for delivery_id in delivery_ids:
            receipt = await session.get(MembershipRenewalDelivery, delivery_id)
            membership = await session.get(Membership, receipt.membership_id)
            player = await MembershipRenewalsService._player(membership.steam_id, session, skip_locked=skip_locked)
            if player is None:
                continue
            await session.refresh(receipt)
            await session.refresh(membership)
            if receipt.cancelled or receipt.activated or not membership.is_scheduled:
                continue
            previous = await session.get(Membership, receipt.previous_membership_id)
            if previous:
                await session.refresh(previous)
            # A late poll never grants an already expired period, but its old VIP
            # still gets a durable removal delivery instead of remaining forever.
            membership.is_scheduled = False
            membership.is_active = membership.end_time is None or MembershipRenewalsService._utc(membership.end_time) > now
            session.add(membership)
            if membership.is_active:
                for role_id in dict.fromkeys((membership.role_granted_id, membership.special_role_id)):
                    if role_id and await session.get(PlayerRole, (membership.steam_id, role_id)) is None:
                        session.add(PlayerRole(steam_id=membership.steam_id, role_id=role_id))
            await session.flush()
            if previous and previous.is_active and previous.end_time and MembershipRenewalsService._utc(previous.end_time) <= now:
                await MembershipsService._deactivate_membership(previous, session)
            receipt.activated = True
            session.add(receipt)
            await session.commit()
            activated += 1
        # Expiration owns a separate receipt ID: a late START acknowledgement can
        # never acknowledge removal of the renewed period's role.
        end_statement = select(MembershipRenewalDelivery.id).where(
            MembershipRenewalDelivery.phase == "END", MembershipRenewalDelivery.activated == False,
            MembershipRenewalDelivery.cancelled == False, MembershipRenewalDelivery.available_at <= now,
        ).order_by(MembershipRenewalDelivery.id)
        if guild_id:
            end_statement = end_statement.where(MembershipRenewalDelivery.guild_id == guild_id)
        for delivery_id in (await session.exec(end_statement)).all():
            receipt = await session.get(MembershipRenewalDelivery, delivery_id)
            membership = await session.get(Membership, receipt.membership_id)
            player = await MembershipRenewalsService._player(membership.steam_id, session, skip_locked=skip_locked)
            if player is None:
                continue
            await session.refresh(receipt)
            await session.refresh(membership)
            if receipt.cancelled or receipt.activated:
                continue
            if membership.end_time and MembershipRenewalsService._utc(membership.end_time) <= now:
                membership.is_scheduled = False
                await MembershipsService._deactivate_membership(membership, session)
                receipt.activated = True
                session.add(receipt)
                await session.commit()
                activated += 1
        return activated

    @staticmethod
    async def _delivery_roles(receipt: MembershipRenewalDelivery, membership: Membership,
                              session: AsyncSession) -> tuple[list[str], list[str]]:
        """Resolve current bindings and never revoke surviving VIP or permanent roles."""
        previous_roles = MembershipRenewalsService._snapshot(receipt.role_ids_to_remove_json)
        planned_roles = MembershipRenewalsService._snapshot(receipt.role_ids_to_add_json)
        logical_ids = [role_id for role_id in (membership.role_granted_id, membership.special_role_id) if role_id]
        player_roles = set((await session.exec(select(PlayerRole.role_id).where(
            PlayerRole.steam_id == membership.steam_id,
        ))).all())
        entitled = [role_id for role_id in logical_ids if role_id in player_roles]
        role_ids_to_add = await MembershipRolesService.resolve_roles(
            receipt.guild_id, entitled, session, lock=False,
        ) if entitled and receipt.phase == "START" else []
        current = datetime.now(timezone.utc)
        vip = await session.get(Role, membership.role_granted_id) if membership.role_granted_id else None
        if not membership.is_active or (membership.end_time and MembershipRenewalsService._utc(membership.end_time) <= current):
            # Remove an expired next-period VIP too if a prior delivery applied it
            # but its acknowledgement was lost. Never remove inherited badges.
            if vip and vip.role_type == "VIP":
                if planned_roles and receipt.phase == "START":
                    previous_roles.append(planned_roles[0])
                role_ids_to_add = [role_id for role_id in role_ids_to_add if role_id not in previous_roles]
        active_memberships = (await session.exec(select(Membership).where(
            Membership.steam_id == membership.steam_id, Membership.is_active == True,
            Membership.start_time <= current, or_(Membership.end_time == None, Membership.end_time > current),
        ))).all()
        active_logical = {role_id for active in active_memberships
                          for role_id in (active.role_granted_id, active.special_role_id) if role_id}
        roles = (await session.exec(select(Role).where(col(Role.id).in_(player_roles)))).all() if player_roles else []
        retained = {role.id for role in roles if role.role_type != "VIP" or role.id in active_logical}
        protected = (await session.exec(select(RoleDiscordBinding.discord_role_id).join(Role).where(
            RoleDiscordBinding.guild_id == receipt.guild_id,
            or_(col(Role.id).in_(retained), col(Role.role_type).in_(["SPECIAL", "SYSTEM"])),
        ))).all()
        remove = [role_id for role_id in dict.fromkeys(previous_roles)
                  if role_id not in set(protected) | set(role_ids_to_add)]
        return role_ids_to_add, remove

    @staticmethod
    async def deliveries(guild_id: str, session: AsyncSession) -> MembershipRenewalDeliveriesResponse:
        MembershipRolesService.require_enabled_guild(guild_id)
        await MembershipRenewalsService.activate_due(session, guild_id, skip_locked=True)
        pending_ids = (await session.exec(select(MembershipRenewalDelivery.id).where(
            MembershipRenewalDelivery.guild_id == guild_id, MembershipRenewalDelivery.activated == True,
            MembershipRenewalDelivery.cancelled == False, MembershipRenewalDelivery.completed == False,
        ).order_by(MembershipRenewalDelivery.id).limit(100))).all()
        result = []
        for delivery_id in pending_ids:
            receipt = await session.get(MembershipRenewalDelivery, delivery_id)
            membership = await session.get(Membership, receipt.membership_id)
            player = await MembershipRenewalsService._player(membership.steam_id, session, skip_locked=True)
            if player is None:
                continue
            await session.refresh(receipt)
            await session.refresh(membership)
            if receipt.completed or receipt.cancelled:
                continue
            if player.discord_id != receipt.user_id or not MembershipsService._valid_discord_id(player.discord_id):
                logger.warning("membership_renewal_delivery_account_changed delivery_id=%s", delivery_id)
                continue
            add, remove = await MembershipRenewalsService._delivery_roles(receipt, membership, session)
            result.append(MembershipRenewalRoleDelivery(
                id=receipt.id, membership_id=membership.id, previous_membership_id=receipt.previous_membership_id,
                steam_id=membership.steam_id, user_id=receipt.user_id, guild_id=receipt.guild_id,
                role_ids_to_add=add, role_ids_to_remove=remove,
            ))
        await session.commit()
        return MembershipRenewalDeliveriesResponse(deliveries=result)

    _warcon_retry_cursor = 0

    @staticmethod
    async def retry_pending(database_engine) -> None:
        """Retry at most two Warcon writes per maintenance cycle, using own sessions.

        The in-memory cursor only provides fairness; durable FAILED state is the
        source of truth and survives restarts. Discord polling never waits here.
        """
        async with AsyncSession(database_engine, expire_on_commit=False) as session:
            candidates = select(MembershipRenewalDelivery.id).join(
                Membership, MembershipRenewalDelivery.membership_id == Membership.id,
            ).where(
                MembershipRenewalDelivery.phase == "START", MembershipRenewalDelivery.cancelled == False,
                Membership.rcon_sync_status != "SUCCESS",
                or_(Membership.is_active == True, Membership.is_scheduled == True),
                or_(Membership.end_time == None, Membership.end_time > datetime.now(timezone.utc)),
            ).order_by(MembershipRenewalDelivery.id)
            ids = (await session.exec(candidates.where(
                MembershipRenewalDelivery.id > MembershipRenewalsService._warcon_retry_cursor,
            ).limit(2))).all()
            if not ids:
                ids = (await session.exec(candidates.limit(2))).all()
        for delivery_id in ids:
            MembershipRenewalsService._warcon_retry_cursor = delivery_id
            try:
                async with AsyncSession(database_engine, expire_on_commit=False) as session:
                    receipt = await session.get(MembershipRenewalDelivery, delivery_id)
                    membership = await session.get(Membership, receipt.membership_id)
                    await MembershipRenewalsService._deliver(membership, receipt, None, session, replayed=True)
            except Exception as exc:
                logger.warning("membership_renewal_warcon_retry_failed delivery_id=%s exception_type=%s",
                               delivery_id, type(exc).__name__)

    @staticmethod
    async def complete(delivery_id: int, req: CompleteMembershipRenewalRequest,
                       session: AsyncSession) -> CompleteMembershipRenewalResponse:
        MembershipRolesService.require_enabled_guild(req.guild_id)
        receipt = await session.get(MembershipRenewalDelivery, delivery_id)
        if not receipt or receipt.guild_id != req.guild_id:
            raise HTTPException(status_code=404, detail={"code": "membership_renewal_delivery_not_found"})
        membership = await session.get(Membership, receipt.membership_id)
        player = await MembershipRenewalsService._player(membership.steam_id, session)
        await session.refresh(receipt)
        if player.discord_id != receipt.user_id:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_delivery_account_changed"})
        if req.user_id is not None and req.user_id != receipt.user_id:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_delivery_account_changed"})
        if receipt.cancelled or not receipt.activated:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_delivery_not_ready"})
        receipt.completed = True
        session.add(receipt)
        await session.commit()
        return CompleteMembershipRenewalResponse(id=delivery_id)
