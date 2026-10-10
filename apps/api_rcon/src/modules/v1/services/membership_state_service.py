"""Describe saved membership periods without changing their lifecycle or benefits."""
import json
from datetime import datetime, timezone
from datetime import datetime as DateTime

from pydantic import ValidationError
from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Membership, MembershipRemovalOperation, MembershipType, Player
from wardogs_schemas.dtos import MembershipStateContext


class MembershipStateService:
    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _discord_id(value: str | None) -> str | None:
        if isinstance(value, str) and value and len(value) <= 20 and value.isascii() and value.isdecimal() and value[0] != "0" and int(value) < 2 ** 64:
            return value
        return None

    @staticmethod
    def _status(membership: Membership, removal: MembershipRemovalOperation | None, now: datetime) -> str:
        end = MembershipStateService._utc(membership.end_time) if membership.end_time else None
        expired = end is not None and end <= now
        future = MembershipStateService._utc(membership.start_time) > now
        # Legacy edits can reactivate a row after a historical removal. Describe
        # current flags/dates before considering that old cancellation receipt.
        if membership.is_scheduled and not expired:
            return "SCHEDULED" if future else "ACTIVATION_PENDING"
        if membership.is_active and not expired:
            return "NOT_STARTED" if future else "ACTIVE"
        if not membership.is_active and not membership.is_scheduled and removal:
            return "REMOVED"
        if expired:
            return "EXPIRED"
        return "INACTIVE"

    @staticmethod
    def removed_membership_ids(operation: MembershipRemovalOperation) -> list[int]:
        """Accept IDs only from a confirmed result belonging to this operation."""
        try:
            result = json.loads(operation.result_json)
        except (TypeError, ValueError):
            return []
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("operation_id") != operation.operation_id or result.get("steam_id") != operation.steam_id:
            return []
        discord = result.get("discord")
        warcon = result.get("warcon")
        if not isinstance(discord, dict) or discord.get("guild_id") != operation.guild_id or discord.get("user_id") != operation.user_id:
            return []
        if not isinstance(warcon, dict) or warcon.get("status") != "SUCCESS":
            return []
        removed_ids = result.get("removed_membership_ids")
        if not isinstance(removed_ids, list):
            return []
        return [value for value in removed_ids
                if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 2 ** 31 - 1]

    @staticmethod
    async def batch(memberships: list[Membership], session: AsyncSession,
                    guild_id: str | None = None) -> dict[int, MembershipStateContext]:
        """Enrich a page with bounded queries; unknown historical causes stay unknown."""
        memberships = [membership for membership in memberships
                       if isinstance(membership.start_time, DateTime)
                       and (membership.end_time is None or isinstance(membership.end_time, DateTime))
                       and isinstance(membership.membership_type, str) and membership.membership_type.strip()]
        if not memberships:
            return {}
        now = datetime.now(timezone.utc)
        steam_ids = {membership.steam_id for membership in memberships}
        members_by_id = {membership.id: membership for membership in memberships}
        codes = {membership.membership_type.strip().upper() for membership in memberships}
        players = (await session.exec(select(Player).where(col(Player.steam_id).in_(steam_ids)))).all()
        players_by_steam = {player.steam_id: player for player in players}
        types = (await session.exec(select(MembershipType).where(func.upper(MembershipType.code).in_(codes)))).all()
        types_by_code = {membership_type.code.upper(): membership_type for membership_type in types}
        operations = select(MembershipRemovalOperation).where(col(MembershipRemovalOperation.steam_id).in_(steam_ids))
        if guild_id is not None:
            operations = operations.where(MembershipRemovalOperation.guild_id == guild_id)
        operations = operations.order_by(col(MembershipRemovalOperation.created_at).desc())
        removals = {}
        for operation in (await session.exec(operations)).all():
            for membership_id in MembershipStateService.removed_membership_ids(operation):
                membership = members_by_id.get(membership_id)
                if membership and membership.steam_id == operation.steam_id and membership_id not in removals:
                    if membership.discord_guild_id is None or membership.discord_guild_id == operation.guild_id:
                        removals[membership_id] = operation
        result = {}
        for membership in memberships:
            membership_type = types_by_code.get(membership.membership_type.strip().upper())
            player = players_by_steam.get(membership.steam_id)
            removal = removals.get(membership.id)
            try:
                status = MembershipStateService._status(membership, removal, now)
                result[membership.id] = MembershipStateContext(
                    id=membership.id, steam_id=membership.steam_id, type=membership.membership_type,
                    type_name=membership_type.name if membership_type else None,
                    discord_id=MembershipStateService._discord_id(player.discord_id) if player else None,
                    status=status, start_date=MembershipStateService._utc(membership.start_time),
                    end_date=MembershipStateService._utc(membership.end_time) if membership.end_time else None,
                    removed_at=MembershipStateService._utc(removal.created_at) if removal and status == "REMOVED" else None,
                    removed_by=MembershipStateService._discord_id(removal.actor_id) if removal and status == "REMOVED" else None,
                )
            except (ValidationError, TypeError, ValueError, AttributeError):
                # Context is optional. Corrupt legacy metadata must not replace
                # the original controlled error with a serialization failure.
                continue
        return result

    @staticmethod
    async def detail(code: str, membership: Membership | None, session: AsyncSession,
                     guild_id: str | None = None) -> dict:
        detail = {"code": code}
        if membership is None or (membership.discord_guild_id and membership.discord_guild_id != guild_id):
            return detail
        contexts = await MembershipStateService.batch([membership], session, guild_id)
        if membership.id in contexts:
            detail["membership"] = contexts[membership.id].model_dump(mode="json")
        return detail

    @staticmethod
    async def latest(steam_id: str, session: AsyncSession, guild_id: str | None = None) -> Membership | None:
        """Choose a visible scheduled period, otherwise the most recent history."""
        statement = select(Membership).where(Membership.steam_id == steam_id, Membership.server_id == None)
        if guild_id is not None:
            statement = statement.where(or_(Membership.discord_guild_id == None, Membership.discord_guild_id == guild_id))
        else:
            statement = statement.where(Membership.discord_guild_id == None)
        return (await session.exec(statement.order_by(
            col(Membership.is_scheduled).desc(), col(Membership.start_time).desc(), col(Membership.id).desc(),
        ).limit(1))).first()
