"""Durable role deliveries shared by immediate memberships and scheduled periods."""
import json
import logging
from datetime import datetime, timezone
from datetime import datetime as DateTime

from fastapi import HTTPException
from sqlmodel import col, or_, select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import (
    Membership, MembershipRenewalDelivery, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding,
)
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.modules.v1.services.memberships_service import MembershipsService
from src.modules.v1.services.membership_state_service import MembershipStateService
from wardogs_schemas.dtos import (
    CompleteMembershipRenewalRequest, CompleteMembershipRenewalResponse,
    AddMembershipResponse, RetryMembershipRequest,
    MembershipRenewalDeliveriesResponse, MembershipRenewalRoleDelivery,
)

logger = logging.getLogger("wardogs.memberships")


class MembershipDeliveriesService:
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
    async def register_initial(membership: Membership, user_id: str, actor_id: str | None,
                               session: AsyncSession) -> MembershipRenewalDelivery:
        """Save both role changes with the membership, before any remote write."""
        role_ids = await MembershipDeliveriesService._roles(membership, membership.discord_guild_id, session)
        receipt = MembershipRenewalDelivery(
            membership_id=membership.id, guild_id=membership.discord_guild_id,
            actor_id=actor_id or "0", user_id=user_id, available_at=membership.start_time,
            activated=True, role_ids_to_add_json=json.dumps(role_ids), role_ids_to_remove_json="[]",
        )
        session.add(receipt)
        if membership.end_time is not None:
            vip_roles = await MembershipDeliveriesService._vip_roles(membership, membership.discord_guild_id, session)
            session.add(MembershipRenewalDelivery(
                membership_id=membership.id, phase="END", guild_id=membership.discord_guild_id,
                actor_id=actor_id or "0", user_id=user_id, available_at=membership.end_time,
                role_ids_to_add_json="[]", role_ids_to_remove_json=json.dumps(vip_roles),
            ))
        return receipt

    @staticmethod
    async def reschedule_initial(membership: Membership, session: AsyncSession) -> None:
        """Keep legacy edits of an initial period aligned with its durable expiry."""
        start = (await session.exec(select(MembershipRenewalDelivery).where(
            MembershipRenewalDelivery.membership_id == membership.id,
            MembershipRenewalDelivery.phase == "START", MembershipRenewalDelivery.previous_membership_id == None,
            MembershipRenewalDelivery.cancelled == False,
        ))).first()
        if not start:
            return
        expiration = (await session.exec(select(MembershipRenewalDelivery).where(
            MembershipRenewalDelivery.membership_id == membership.id, MembershipRenewalDelivery.phase == "END",
        ))).first()
        if expiration and (expiration.activated or expiration.completed):
            raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                "membership_expiration_finalized", membership, session, membership.discord_guild_id,
            ))
        if membership.end_time is None:
            if expiration:
                expiration.cancelled = True
                session.add(expiration)
        else:
            if not expiration:
                expiration = MembershipRenewalDelivery(
                    membership_id=membership.id, phase="END", guild_id=start.guild_id,
                    actor_id=start.actor_id, user_id=start.user_id, role_ids_to_add_json="[]",
                    available_at=membership.end_time, role_ids_to_remove_json="[]",
                )
            expiration.available_at = membership.end_time
            expiration.cancelled = not membership.is_active
            expiration.role_ids_to_remove_json = json.dumps(await MembershipDeliveriesService._vip_roles(membership, start.guild_id, session))
            session.add(expiration)
        membership.rcon_sync_status = "PENDING"
        session.add(membership)

    @staticmethod
    async def retry(membership_id: int, req: RetryMembershipRequest, session: AsyncSession) -> AddMembershipResponse:
        """Repair the existing initial grant without changing its duration or identity."""
        MembershipRolesService.require_enabled_guild(req.guild_id)
        membership = await session.get(Membership, membership_id)
        if not membership:
            raise HTTPException(status_code=404, detail={"code": "membership_retry_not_found"})
        if membership.discord_guild_id != req.guild_id:
            raise HTTPException(status_code=409, detail={"code": "membership_retry_other_guild"})
        now = datetime.now(timezone.utc)
        if not membership.is_active or not isinstance(membership.start_time, DateTime) or MembershipDeliveriesService._utc(membership.start_time) > now or (membership.end_time and MembershipDeliveriesService._utc(membership.end_time) <= now):
            raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                "membership_retry_unavailable", membership, session, req.guild_id,
            ))
        player = await MembershipDeliveriesService._player(membership.steam_id, session)
        await session.refresh(membership)
        receipt = (await session.exec(select(MembershipRenewalDelivery).where(
            MembershipRenewalDelivery.membership_id == membership_id,
            MembershipRenewalDelivery.phase == "START",
        ))).first()
        if not receipt or receipt.previous_membership_id is not None or receipt.cancelled:
            raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                "membership_retry_unsupported", membership, session, req.guild_id,
            ))
        result = await MembershipsService._deliver_discord_membership(
            membership, player, session, replayed=True, guild_id=req.guild_id,
        )
        logger.info("membership_retry actor_id=%s guild_id=%s membership_id=%s warcon_status=%s",
                    req.actor_id, req.guild_id, membership.id, result.warcon.status)
        return result

    @staticmethod
    async def role_delivery(receipt: MembershipRenewalDelivery, membership: Membership,
                            session: AsyncSession) -> MembershipRenewalRoleDelivery:
        add, remove = await MembershipDeliveriesService._delivery_roles(receipt, membership, session)
        return MembershipRenewalRoleDelivery(
            id=receipt.id, membership_id=membership.id, previous_membership_id=receipt.previous_membership_id,
            steam_id=membership.steam_id, user_id=receipt.user_id, guild_id=receipt.guild_id,
            role_ids_to_add=add, role_ids_to_remove=remove,
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
    async def activate_due(session: AsyncSession, guild_id: str | None = None, skip_locked: bool = False,
                           steam_id: str | None = None) -> int:
        """Make due periods current before expiry removes the previous role entitlement."""
        now = datetime.now(timezone.utc)
        statement = select(MembershipRenewalDelivery.id).join(Membership, MembershipRenewalDelivery.membership_id == Membership.id).where(
            MembershipRenewalDelivery.activated == False, MembershipRenewalDelivery.cancelled == False,
            MembershipRenewalDelivery.phase == "START",
            MembershipRenewalDelivery.available_at <= now, Membership.is_scheduled == True,
        ).order_by(MembershipRenewalDelivery.id)
        if guild_id:
            statement = statement.where(MembershipRenewalDelivery.guild_id == guild_id)
        if steam_id is not None:
            statement = statement.where(Membership.steam_id == steam_id)
        delivery_ids = (await session.exec(statement)).all()
        activated = 0
        for delivery_id in delivery_ids:
            receipt = await session.get(MembershipRenewalDelivery, delivery_id)
            membership = await session.get(Membership, receipt.membership_id)
            player = await MembershipDeliveriesService._player(membership.steam_id, session, skip_locked=skip_locked)
            if player is None:
                continue
            await session.refresh(receipt)
            await session.refresh(membership)
            if receipt.cancelled or receipt.activated or not membership.is_scheduled:
                continue
            previous = await session.get(Membership, receipt.previous_membership_id) if receipt.previous_membership_id else None
            if previous:
                await session.refresh(previous)
            # A late poll never grants an already expired period, but its old VIP
            # still gets a durable removal delivery instead of remaining forever.
            membership.is_scheduled = False
            membership.is_active = membership.end_time is None or MembershipDeliveriesService._utc(membership.end_time) > now
            session.add(membership)
            if membership.is_active:
                for role_id in dict.fromkeys((membership.role_granted_id, membership.special_role_id)):
                    if role_id and await session.get(PlayerRole, (membership.steam_id, role_id)) is None:
                        session.add(PlayerRole(steam_id=membership.steam_id, role_id=role_id))
            await session.flush()
            if previous and previous.is_active and previous.end_time and MembershipDeliveriesService._utc(previous.end_time) <= now:
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
        if steam_id is not None:
            end_statement = end_statement.join(Membership, MembershipRenewalDelivery.membership_id == Membership.id).where(Membership.steam_id == steam_id)
        for delivery_id in (await session.exec(end_statement)).all():
            receipt = await session.get(MembershipRenewalDelivery, delivery_id)
            membership = await session.get(Membership, receipt.membership_id)
            player = await MembershipDeliveriesService._player(membership.steam_id, session, skip_locked=skip_locked)
            if player is None:
                continue
            await session.refresh(receipt)
            await session.refresh(membership)
            if receipt.cancelled or receipt.activated:
                continue
            if membership.end_time and MembershipDeliveriesService._utc(membership.end_time) <= now:
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
        previous_roles = MembershipDeliveriesService._snapshot(receipt.role_ids_to_remove_json)
        MembershipDeliveriesService._snapshot(receipt.role_ids_to_add_json)
        logical_ids = [role_id for role_id in (membership.role_granted_id, membership.special_role_id) if role_id]
        player_roles = set((await session.exec(select(PlayerRole.role_id).where(
            PlayerRole.steam_id == membership.steam_id,
        ))).all())
        entitled = [role_id for role_id in logical_ids if role_id in player_roles]
        current = datetime.now(timezone.utc)
        current_period = membership.is_active and (membership.end_time is None or MembershipDeliveriesService._utc(membership.end_time) > current)
        role_ids_to_add = await MembershipRolesService.resolve_roles(
            receipt.guild_id, entitled, session, lock=False,
        ) if entitled and receipt.phase == "START" and current_period else []
        vip = await session.get(Role, membership.role_granted_id) if membership.role_granted_id else None
        if not membership.is_active or (membership.end_time and MembershipDeliveriesService._utc(membership.end_time) <= current):
            # Remove an expired next-period VIP too if a prior delivery applied it
            # but its acknowledgement was lost. Never remove inherited badges.
            if vip and vip.role_type == "VIP":
                if receipt.phase == "START":
                    expiration = (await session.exec(select(MembershipRenewalDelivery).where(
                        MembershipRenewalDelivery.membership_id == membership.id,
                        MembershipRenewalDelivery.phase == "END",
                    ))).first()
                    if expiration:
                        previous_roles.extend(MembershipDeliveriesService._snapshot(expiration.role_ids_to_remove_json))
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
        await MembershipDeliveriesService.activate_due(session, guild_id, skip_locked=True)
        pending_ids = (await session.exec(select(MembershipRenewalDelivery.id).where(
            MembershipRenewalDelivery.guild_id == guild_id, MembershipRenewalDelivery.activated == True,
            MembershipRenewalDelivery.cancelled == False, MembershipRenewalDelivery.completed == False,
        ).order_by(MembershipRenewalDelivery.id).limit(100))).all()
        result = []
        for delivery_id in pending_ids:
            receipt = await session.get(MembershipRenewalDelivery, delivery_id)
            membership = await session.get(Membership, receipt.membership_id)
            player = await MembershipDeliveriesService._player(membership.steam_id, session, skip_locked=True)
            if player is None:
                continue
            await session.refresh(receipt)
            await session.refresh(membership)
            if receipt.completed or receipt.cancelled:
                continue
            if player.discord_id != receipt.user_id or not MembershipsService._valid_discord_id(player.discord_id):
                logger.warning("membership_renewal_delivery_account_changed delivery_id=%s", delivery_id)
                continue
            try:
                result.append(await MembershipDeliveriesService.role_delivery(receipt, membership, session))
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                logger.warning("membership_delivery_configuration_missing delivery_id=%s", delivery_id)
        await session.commit()
        return MembershipRenewalDeliveriesResponse(deliveries=result)

    @staticmethod
    async def delivery(delivery_id: int, guild_id: str, session: AsyncSession) -> MembershipRenewalRoleDelivery:
        """Revalidate a polled receipt immediately before the bot changes roles."""
        MembershipRolesService.require_enabled_guild(guild_id)
        receipt = await session.get(MembershipRenewalDelivery, delivery_id)
        if not receipt or receipt.guild_id != guild_id:
            raise HTTPException(status_code=404, detail={"code": "membership_delivery_not_found"})
        membership = await session.get(Membership, receipt.membership_id)
        # Refresh the player's complete chain so the next START takes effect
        # before an old END considers withdrawing a continuously held VIP role.
        await MembershipDeliveriesService.activate_due(session, guild_id, skip_locked=True,
                                                        steam_id=membership.steam_id)
        player = await MembershipDeliveriesService._player(membership.steam_id, session, skip_locked=True)
        if player is None:
            raise HTTPException(status_code=404, detail={"code": "membership_delivery_not_ready"})
        await session.refresh(receipt)
        await session.refresh(membership)
        if receipt.completed or receipt.cancelled or not receipt.activated:
            raise HTTPException(status_code=404, detail={"code": "membership_delivery_not_ready"})
        if player.discord_id != receipt.user_id or not MembershipsService._valid_discord_id(player.discord_id):
            raise HTTPException(status_code=409, detail={"code": "membership_delivery_account_changed"})
        result = await MembershipDeliveriesService.role_delivery(receipt, membership, session)
        await session.commit()
        return result

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
                MembershipRenewalDelivery.id > MembershipDeliveriesService._warcon_retry_cursor,
            ).limit(2))).all()
            if not ids:
                ids = (await session.exec(candidates.limit(2))).all()
        for delivery_id in ids:
            MembershipDeliveriesService._warcon_retry_cursor = delivery_id
            try:
                async with AsyncSession(database_engine, expire_on_commit=False) as session:
                    receipt = await session.get(MembershipRenewalDelivery, delivery_id)
                    membership = await session.get(Membership, receipt.membership_id)
                    player = await MembershipDeliveriesService._player(membership.steam_id, session, skip_locked=True)
                    if player is None:
                        continue
                    await session.refresh(receipt)
                    await session.refresh(membership)
                    now = datetime.now(timezone.utc)
                    if receipt.cancelled or membership.server_id is not None or membership.rcon_sync_status == "SUCCESS" or not (membership.is_active or membership.is_scheduled):
                        continue
                    if membership.end_time and MembershipDeliveriesService._utc(membership.end_time) <= now:
                        continue
                    await MembershipsService._require_no_pending_removal(membership.steam_id, session)
                    if player.discord_id != receipt.user_id:
                        continue
                    membership_type = (await session.exec(select(MembershipType).where(
                        func.upper(MembershipType.code) == membership.membership_type.strip().upper(),
                    ))).first()
                    if not membership_type:
                        continue
                    expiries = (await session.exec(select(Membership.end_time).where(
                        Membership.steam_id == membership.steam_id, Membership.server_id == None,
                        or_(Membership.is_active == True, Membership.is_scheduled == True),
                        or_(Membership.end_time == None, Membership.end_time > now),
                    ))).all()
                    warcon = await WarconClient().upsert_reserved_slot(
                        membership.steam_id, membership.id, membership_type.name,
                        MembershipsService._effective_slot_expiry(expiries),
                    )
                    membership.rcon_sync_status = warcon.status
                    session.add(membership)
                    await session.commit()
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
        player = await MembershipDeliveriesService._player(membership.steam_id, session)
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
