"""Cancel one player's memberships inline; the bot owns the final Discord role removal."""
import hashlib
import json
import logging

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import (
    Membership, MembershipRemovalOperation, MembershipRenewalDelivery, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding,
)
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.modules.v1.services.memberships_service import MembershipsService
from wardogs_schemas.dtos import (
    CompleteMembershipRemovalRequest, CompleteMembershipRemovalResponse,
    MembershipDiscordDelivery, RemoveMembershipRequest, RemoveMembershipResponse,
)

logger = logging.getLogger("wardogs.memberships")


class MembershipRemovalsService:
    @staticmethod
    async def _player(steam_id: str, session: AsyncSession) -> Player:
        player = (await session.exec(select(Player).where(
            Player.steam_id == steam_id,
        ).with_for_update().execution_options(populate_existing=True))).first()
        if not player:
            raise HTTPException(status_code=404, detail={"code": "membership_removal_player_not_found"})
        return player

    @staticmethod
    async def _replay(operation: MembershipRemovalOperation, player: Player, session: AsyncSession) -> RemoveMembershipResponse:
        if not MembershipsService._valid_discord_id(player.discord_id) or player.discord_id != operation.user_id:
            raise HTTPException(status_code=409, detail={"code": "membership_removal_discord_account_missing"})
        # A completed receipt must never revoke a newer membership or rewrite Warcon.
        active = (await session.exec(select(Membership.id).where(
            Membership.steam_id == operation.steam_id,
            or_(Membership.is_active == True, Membership.is_scheduled == True),
            Membership.server_id == None,
        ).limit(1))).first()
        if active:
            raise HTTPException(status_code=409, detail={"code": "membership_removal_superseded"})
        response = RemoveMembershipResponse.model_validate_json(operation.result_json)
        if operation.discord_roles_removed:
            response.discord = response.discord.model_copy(update={"role_ids": []})
        return response.model_copy(update={"replayed": True})

    @staticmethod
    async def _logical_roles(memberships: list[Membership], session: AsyncSession,
                             include_special: bool = True) -> set[int]:
        codes = {membership.membership_type.strip().upper() for membership in memberships if not membership.role_granted_id}
        types = (await session.exec(select(MembershipType).where(
            func.upper(MembershipType.code).in_(codes),
        ))).all() if codes else []
        fallback = {m_type.code.upper(): m_type.role_id for m_type in types}
        roles = set()
        for membership in memberships:
            primary = membership.role_granted_id or fallback.get(membership.membership_type.strip().upper())
            if primary:
                roles.add(primary)
            if include_special and membership.special_role_id:
                roles.add(membership.special_role_id)
        return roles

    @staticmethod
    async def _roles_to_remove(guild_id: str, selected: list[Membership], all_memberships: list[Membership],
                               session: AsyncSession) -> list[str]:
        """Only configured VIP roles without surviving or permanent entitlements are revocable."""
        logical_ids = await MembershipRemovalsService._logical_roles(selected, session, include_special=False)
        if not logical_ids:
            return []
        roles = (await session.exec(select(Role).where(col(Role.id).in_(logical_ids))
                                   .order_by(Role.id).with_for_update())).all()
        vip_ids = [role.id for role in roles if role.role_type == "VIP"]
        if not vip_ids:
            return []
        try:
            candidate_ids = await MembershipRolesService.resolve_roles(guild_id, vip_ids, session, lock=False)
        except HTTPException as exc:
            if exc.status_code == 409:
                raise HTTPException(status_code=409, detail={"code": "membership_removal_role_configuration_missing"}) from None
            raise

        selected_ids = {membership.id for membership in selected}
        remaining = [membership for membership in all_memberships
                     if membership.is_active and membership.id not in selected_ids]
        retained_logical_ids = await MembershipRemovalsService._logical_roles(remaining, session)
        retained_logical_ids.update(membership.special_role_id for membership in selected if membership.special_role_id)
        # A Discord ID shared with a staff/special binding remains protected even if
        # an incorrectly configured VIP type points to that same physical role.
        protected = (await session.exec(select(Role.id).where(
            col(Role.role_type).in_(["SPECIAL", "SYSTEM"]),
        ))).all()
        retained_logical_ids.update(protected)
        retained_bindings = (await session.exec(select(RoleDiscordBinding.discord_role_id).where(
            RoleDiscordBinding.guild_id == guild_id,
            col(RoleDiscordBinding.role_id).in_(retained_logical_ids),
        ))).all() if retained_logical_ids else []
        return [role_id for role_id in candidate_ids if role_id not in set(retained_bindings)]

    @staticmethod
    async def remove(steam_id: str, req: RemoveMembershipRequest, session: AsyncSession) -> RemoveMembershipResponse:
        MembershipRolesService.require_enabled_guild(req.guild_id)
        player = await MembershipRemovalsService._player(steam_id, session)
        await MembershipsService._require_no_pending_renewal_delivery(steam_id, session)
        request_hash = hashlib.sha256(json.dumps({"steam_id": steam_id, "guild_id": req.guild_id}, sort_keys=True).encode()).hexdigest()
        previous = await session.get(MembershipRemovalOperation, req.operation_id)
        if previous:
            if previous.request_hash != request_hash:
                raise HTTPException(status_code=409, detail={"code": "membership_removal_operation_conflict"})
            return await MembershipRemovalsService._replay(previous, player, session)
        pending = (await session.exec(select(MembershipRemovalOperation).where(
            MembershipRemovalOperation.steam_id == steam_id,
            MembershipRemovalOperation.discord_roles_removed == False,
        ).order_by(MembershipRemovalOperation.created_at.desc()).limit(1))).first()
        if pending:
            if pending.guild_id != req.guild_id:
                raise HTTPException(status_code=409, detail={"code": "membership_removal_pending_other_guild"})
            return await MembershipRemovalsService._replay(pending, player, session)
        if not MembershipsService._valid_discord_id(player.discord_id):
            raise HTTPException(status_code=409, detail={"code": "membership_removal_discord_account_missing"})

        memberships = (await session.exec(select(Membership).where(
            Membership.steam_id == steam_id,
        ).order_by(Membership.id).execution_options(populate_existing=True))).all()
        selected = [membership for membership in memberships
                    if (membership.is_active or membership.is_scheduled) and membership.server_id is None]
        if any(membership.discord_guild_id and membership.discord_guild_id != req.guild_id for membership in selected):
            raise HTTPException(status_code=409, detail={"code": "membership_removal_other_guild"})
        if not selected:
            raise HTTPException(status_code=404, detail={"code": "membership_removal_not_found"})
        role_ids = await MembershipRemovalsService._roles_to_remove(req.guild_id, selected, memberships, session)
        special_ids = {membership.special_role_id for membership in selected if membership.special_role_id}
        preserved_badges = (await session.exec(select(PlayerRole.role_id).where(
            PlayerRole.steam_id == steam_id, col(PlayerRole.role_id).in_(special_ids),
        ))).all() if special_ids else []
        warcon_client = WarconClient()
        warcon_client.validate_configuration()
        operation = MembershipRemovalOperation(
            operation_id=req.operation_id, request_hash=request_hash, steam_id=steam_id,
            guild_id=req.guild_id, actor_id=req.actor_id, user_id=player.discord_id,
            result_json="{}", discord_roles_removed=not role_ids,
        )
        session.add(operation)
        # Reserve the operation ID before remote I/O, including requests for different
        # players racing with the same ID. A failure rolls this insertion back.
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail={"code": "membership_removal_operation_conflict"}) from None
        warcon = await warcon_client.remove_reserved_slot(
            steam_id=steam_id,
            membership_ids=[membership.id for membership in memberships if membership.server_id is None],
        )
        if warcon.status != "SUCCESS":
            await session.rollback()
            raise HTTPException(status_code=502, detail={"code": "membership_removal_warcon_failed"})
        # Mark the complete selection first so duplicate legacy memberships cannot
        # keep each other's PlayerRole alive during the existing revocation checks.
        for membership in selected:
            membership.is_active = False
            membership.is_scheduled = False
            membership.rcon_sync_status = "SUCCESS"
            session.add(membership)
        renewals = (await session.exec(select(MembershipRenewalDelivery).where(
            col(MembershipRenewalDelivery.membership_id).in_([membership.id for membership in selected]),
        ))).all()
        for renewal in renewals:
            renewal.cancelled = True
            session.add(renewal)
        await session.flush()
        for membership in selected:
            await MembershipsService._deactivate_membership(membership, session)
        await session.flush()
        # A legacy badge can share a logical VIP role with another cancelled plan.
        # Restore only badges this player already had, preserving the existing policy.
        for role_id in preserved_badges:
            if await session.get(PlayerRole, (steam_id, role_id)) is None:
                session.add(PlayerRole(steam_id=steam_id, role_id=role_id))
        response = RemoveMembershipResponse(
            steam_id=steam_id, operation_id=req.operation_id,
            removed_membership_ids=[membership.id for membership in selected],
            discord=MembershipDiscordDelivery(user_id=player.discord_id, guild_id=req.guild_id, role_ids=role_ids),
            warcon=warcon,
        )
        operation.result_json = response.model_dump_json()
        session.add(operation)
        await session.commit()
        logger.info("membership_removal actor_id=%s guild_id=%s steam_id=%s operation_id=%s membership_ids=%s",
                    req.actor_id, req.guild_id, steam_id, req.operation_id, response.removed_membership_ids)
        return response

    @staticmethod
    async def complete(steam_id: str, operation_id: str, req: CompleteMembershipRemovalRequest,
                       session: AsyncSession) -> CompleteMembershipRemovalResponse:
        MembershipRolesService.require_enabled_guild(req.guild_id)
        await MembershipRemovalsService._player(steam_id, session)
        operation = await session.get(MembershipRemovalOperation, operation_id)
        if not operation:
            raise HTTPException(status_code=404, detail={"code": "membership_removal_operation_not_found"})
        if operation.steam_id != steam_id or operation.guild_id != req.guild_id:
            raise HTTPException(status_code=409, detail={"code": "membership_removal_operation_conflict"})
        operation.discord_roles_removed = True
        session.add(operation)
        await session.commit()
        logger.info("membership_removal_completed actor_id=%s guild_id=%s steam_id=%s operation_id=%s",
                    req.actor_id, req.guild_id, steam_id, operation_id)
        return CompleteMembershipRemovalResponse(operation_id=operation_id)
