"""Schedule membership periods; Python owns dates/Warcon and the bot delivers roles."""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import (
    Membership, MembershipRenewalDelivery, MembershipType, Player,
)
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.modules.v1.services.memberships_service import MembershipsService
from src.modules.v1.services.membership_state_service import MembershipStateService
from src.modules.v1.services.membership_deliveries_service import MembershipDeliveriesService
from wardogs_schemas.dtos import (
    CreatedMembershipItem, MembershipDiscordDelivery,
    RenewMembershipRequest, RenewMembershipResponse,
)

logger = logging.getLogger("wardogs.memberships")


class MembershipRenewalsService:
    @staticmethod
    async def renew(req: RenewMembershipRequest, session: AsyncSession) -> RenewMembershipResponse:
        MembershipRolesService.require_enabled_guild(req.guild_id)
        player = await MembershipDeliveriesService._player(req.steam_id, session)
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
                raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                    "membership_renewal_cancelled", previous_operation, session, req.guild_id,
                ))
            return await MembershipRenewalsService._deliver(previous_operation, receipt, player, session, replayed=True)

        await MembershipsService._require_no_pending_removal(req.steam_id, session, guild_id=req.guild_id)
        await MembershipsService._require_no_pending_renewal_delivery(req.steam_id, session, guild_id=req.guild_id)
        if not MembershipsService._valid_discord_id(player.discord_id):
            raise HTTPException(status_code=409, detail="El jugador no tiene una cuenta de Discord válida vinculada.")
        pending = (await session.exec(select(Membership.id).where(
            Membership.steam_id == req.steam_id, Membership.is_scheduled == True,
        ).limit(1))).first()
        if pending:
            raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                "membership_renewal_already_scheduled", await session.get(Membership, pending), session, req.guild_id,
            ))

        now = datetime.now(timezone.utc)
        current = (await session.exec(select(Membership).where(
            Membership.steam_id == req.steam_id, Membership.is_active == True,
            Membership.start_time <= now, or_(Membership.end_time == None, Membership.end_time > now),
        ).order_by(Membership.id).execution_options(populate_existing=True))).all()
        if not current:
            raise HTTPException(status_code=404, detail=await MembershipStateService.detail(
                "membership_renewal_not_found", await MembershipStateService.latest(req.steam_id, session, req.guild_id), session, req.guild_id,
            ))
        if len(current) != 1 or current[0].server_id is not None:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_ambiguous"})
        previous = current[0]
        if previous.discord_guild_id and previous.discord_guild_id != req.guild_id:
            raise HTTPException(status_code=409, detail={"code": "membership_renewal_other_guild"})
        if previous.end_time is None:
            raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                "membership_renewal_permanent", previous, session, req.guild_id,
            ))
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
        start = MembershipDeliveriesService._utc(previous.end_time)
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
        new_roles = await MembershipDeliveriesService._roles(membership, req.guild_id, session)
        old_roles = await MembershipDeliveriesService._vip_roles(previous, req.guild_id, session)
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
            next_vip = await MembershipDeliveriesService._vip_roles(membership, req.guild_id, session)
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
        player = await MembershipDeliveriesService._player(membership.steam_id, session)
        await session.refresh(membership)
        await session.refresh(receipt)
        await MembershipsService._require_no_pending_removal(membership.steam_id, session, guild_id=receipt.guild_id)
        if receipt.cancelled or (not membership.is_active and not membership.is_scheduled):
            raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                "membership_renewal_cancelled", membership, session, receipt.guild_id,
            ))
        now = datetime.now(timezone.utc)
        if membership.end_time and MembershipDeliveriesService._utc(membership.end_time) <= now:
            raise HTTPException(status_code=409, detail=await MembershipStateService.detail(
                "membership_renewal_unavailable", membership, session, receipt.guild_id,
            ))
        if not MembershipsService._valid_discord_id(player.discord_id) or player.discord_id != receipt.user_id:
            raise HTTPException(status_code=409, detail="El jugador ya no tiene la misma cuenta de Discord vinculada.")
        m_type = (await session.exec(select(MembershipType).where(
            func.upper(MembershipType.code) == membership.membership_type.strip().upper(),
        ))).first()
        if not m_type:
            raise HTTPException(status_code=409, detail="El tipo de esta membresía ya no está registrado en nuestro sistema.")
        await MembershipDeliveriesService._roles(membership, receipt.guild_id, session)
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
                start_date=MembershipDeliveriesService._utc(membership.start_time),
                end_date=MembershipDeliveriesService._utc(membership.end_time) if membership.end_time else None,
                is_booster=membership.is_booster, server_id=membership.server_id,
            ),
            discord=MembershipDiscordDelivery(user_id=receipt.user_id, guild_id=receipt.guild_id, role_ids=[]),
            warcon=warcon, replayed=replayed,
        )


    # Existing callers retain their entry points while deliveries serve all periods.
    activate_due = staticmethod(MembershipDeliveriesService.activate_due)
    deliveries = staticmethod(MembershipDeliveriesService.deliveries)
    retry_pending = staticmethod(MembershipDeliveriesService.retry_pending)
    complete = staticmethod(MembershipDeliveriesService.complete)
