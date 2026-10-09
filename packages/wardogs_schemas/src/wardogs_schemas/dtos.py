from __future__ import annotations
from typing import Annotated, Any, List, Literal, Optional
from datetime import datetime
from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_serializer, model_validator


def _valid_snowflake(value: str) -> str:
    if int(value) >= 2 ** 64:
        raise ValueError("Discord IDs must fit an unsigned 64-bit integer")
    return value


DiscordSnowflake = Annotated[
    str, Field(strict=True, min_length=1, max_length=20, pattern=r"^[1-9][0-9]*$"),
    AfterValidator(_valid_snowflake),
]


DatabaseId = Annotated[int, Field(ge=1, le=2 ** 31 - 1)]


# ---------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------

class ConfigUpdateRequest(BaseModel):
    revision: str
    new_text: str


class LinkAccountRequest(BaseModel):
    discord_id: str
    steam_id: str


class UnlinkAccountRequest(BaseModel):
    discord_id: str


class EditPlayerRequest(BaseModel):
    discord_id: str | None = None
    custom_welcome_message: str | None = None
    observations: str | None = None


class AddMembershipRequest(BaseModel):
    steam_id: str
    membership_type: str
    days: Optional[int] = None
    special_role: Optional[str] = None
    special_role_id: Optional[DatabaseId] = None
    role_granted_id: Optional[DatabaseId] = None
    is_booster: Optional[bool] = False
    server_id: Optional[int] = None
    payment_source: Optional[str] = "MANUAL"
    guild_id: Optional[DiscordSnowflake] = None
    source: Optional[Literal["DISCORD"]] = None
    operation_id: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_discord_operation(self):
        if self.source == "DISCORD" and not self.operation_id:
            raise ValueError("operation_id is required for Discord membership creation")
        return self


class CreatedMembershipItem(BaseModel):
    id: int
    steam_id: str
    type: str
    start_date: datetime
    end_date: Optional[datetime] = None
    is_booster: bool
    server_id: Optional[int] = None


class MembershipDiscordDelivery(BaseModel):
    user_id: str
    role_ids: List[str]
    guild_id: Optional[DiscordSnowflake] = None

    @model_serializer(mode="wrap")
    def omit_legacy_guild(self, handler):
        result = handler(self)
        if self.guild_id is None:
            result.pop("guild_id", None)
        return result


class ConfigureMembershipRoleRequest(BaseModel):
    discord_role_id: DiscordSnowflake
    actor_id: DiscordSnowflake


class MembershipRoleConfiguration(BaseModel):
    guild_id: DiscordSnowflake
    membership_type: str
    membership_type_name: str
    role_id: int
    discord_role_id: DiscordSnowflake
    configured_by: DiscordSnowflake
    changed: bool = False


class UnassignMembershipRoleRequest(BaseModel):
    actor_id: DiscordSnowflake


class MembershipRoleUnassignment(BaseModel):
    guild_id: DiscordSnowflake
    membership_type: str
    membership_type_name: str
    role_id: DatabaseId
    discord_role_id: Optional[DiscordSnowflake] = None
    actor_id: DiscordSnowflake
    changed: bool

    @model_validator(mode="after")
    def require_previous_role_when_changed(self):
        if self.changed != (self.discord_role_id is not None):
            raise ValueError("Only a changed unassignment must include the previous Discord role ID")
        return self


class MembershipWarconDelivery(BaseModel):
    status: Literal["SUCCESS", "FAILED"]
    server_id: str
    entry_id: Optional[str] = None
    error: Optional[str] = None


class AddMembershipResponse(BaseModel):
    ok: bool
    message: str
    membership: Optional[CreatedMembershipItem] = None
    discord: Optional[MembershipDiscordDelivery] = None
    warcon: Optional[MembershipWarconDelivery] = None
    replayed: bool = False


class EditMembershipRequest(BaseModel):
    days: Optional[int] = None
    add_days: Optional[int] = None
    membership_type: Optional[str] = None
    is_active: Optional[bool] = None
    is_booster: Optional[bool] = None
    server_id: Optional[DatabaseId] = None


class CompensateRequest(BaseModel):
    days: int


class SetBotConfigRequest(BaseModel):
    key: str
    value: str


class QuotaUpdateRequest(BaseModel):
    max_quota: Optional[int] = Field(ge=0, le=2 ** 31 - 1)


class RoleRegisterRequest(BaseModel):
    code: str
    name: str
    role_type: str
    discord_role_id: str | None = None



class CreateRconServerRequest(BaseModel):
    ip: str
    port: int
    password: str
    name: str | None = None
    scheme: str = "http"
    is_active: bool = True
    is_default: bool = False


class UpdateRconServerRequest(BaseModel):
    name: str | None = None
    ip: str | None = None
    port: int | None = None
    password: str | None = None
    scheme: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class CreateMembershipTypeRequest(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    description: Optional[str] = None
    price_usd: float = Field(default=0.0, ge=0, le=21474836.47, allow_inf_nan=False)  # USD units
    price_ars: Optional[float] = Field(default=None, ge=0, le=21474836.47, allow_inf_nan=False)  # ARS units
    billing_type: str = "ONE_TIME"  # "ONE_TIME" or "RECURRING"
    default_days: int = Field(default=30, ge=0, le=2147483647)  # 0 = permanente
    max_quota: Optional[int] = Field(default=None, ge=0, le=2147483647) # None = ilimitado
    discord_role_id: Optional[str] = None
    role_id: Optional[DatabaseId] = None
    server_id: Optional[DatabaseId] = None
    is_active: bool = True


class UpdateMembershipTypeRequest(BaseModel):
    name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]] = None
    description: Optional[str] = None
    price_usd: Optional[float] = Field(default=None, ge=0, le=21474836.47, allow_inf_nan=False)
    price_ars: Optional[float] = Field(default=None, ge=0, le=21474836.47, allow_inf_nan=False)
    billing_type: Optional[str] = None
    default_days: Optional[int] = Field(default=None, ge=0, le=2147483647)
    max_quota: Optional[int] = Field(default=None, ge=0, le=2147483647)
    discord_role_id: Optional[str] = None
    role_id: Optional[DatabaseId] = None
    server_id: Optional[DatabaseId] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------

class MembershipTypeItem(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    price_usd: float = 0.0
    price_ars: Optional[float] = None
    billing_type: str = "ONE_TIME"
    default_days: int = 30
    max_quota: int | None = None
    current_usage: int = 0
    discord_role_id: str | None = None
    role_id: int | None = None
    role_name: str | None = None
    server_id: int | None = None
    server_name: str | None = None
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class MembershipTypeActionResponse(BaseModel):
    ok: bool
    message: str
    membership_type: MembershipTypeItem | None = None


class RconServerItem(BaseModel):
    id: int
    name: str
    ip: str
    port: int
    scheme: str = "http"
    base_url: str
    is_active: bool = True
    is_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    is_online: bool | None = None
    current_map: str | None = None
    player_count: int | None = None
    max_players: int | None = None
    ping_ms: float | None = None


class RconServerActionResponse(BaseModel):
    ok: bool
    message: str
    server: RconServerItem | None = None


class RconServerTestResponse(BaseModel):
    ok: bool
    is_online: bool
    latency_ms: float | None = None
    server_id: int
    name: str
    server_name: str | None = None
    current_map: str | None = None
    player_count: int | None = None
    max_players: int | None = None
    match_seconds: int | None = None
    error: str | None = None


class RconServerSyncResultItem(BaseModel):
    server_id: int
    server_name: str
    base_url: str
    status: str
    vip_slots_synced: int = 0
    bans_synced: int = 0
    error: str | None = None


class RconServersSyncAllResponse(BaseModel):
    ok: bool
    message: str
    results: list[RconServerSyncResultItem] = Field(default_factory=list)


class ExportMembershipsResponse(BaseModel):
    ok: bool
    filename: str
    total_records: int
    size_bytes: int
    download_url: str
    expires_in_seconds: int = 1800


# ---------------------------------------------------------
# Squad Schemas
# ---------------------------------------------------------

class SquadData(BaseModel):
    id: str
    name: str
    tag: str
    leader_steam_id: str
    total_kills: int = 0
    total_deaths: int = 0
    total_cash_earned: int = 0
    total_matches_played: int = 0
    created_at: str | None = None


class SquadMemberData(BaseModel):
    steam_id: str
    in_game_name: str
    kills: int = 0
    deaths: int = 0
    cash: int = 0


# ---------------------------------------------------------
# Rewards Schemas
# ---------------------------------------------------------

class CreateRewardItemRequest(BaseModel):
    code: str
    name: str
    description: str | None = None
    cost_points: int = Field(default=1, ge=1)
    delivery_type: str = Field(default="AUTOMATIC") # AUTOMATIC or MANUAL_TICKET
    reward_type: str = Field(default="MEMBERSHIP")  # MEMBERSHIP, ROLE, CUSTOM
    reward_value: str = Field(default="")
    duration_days: int | None = None
    is_active: bool = True


class ClaimRewardRequest(BaseModel):
    player_identifier: str
    reward_code: str


class DeliverClaimRequest(BaseModel):
    delivered_by: str
    notes: str | None = None


class RefundClaimRequest(BaseModel):
    refunded_by: str
    reason: str | None = None


class GiveRewardPointsRequest(BaseModel):
    player_identifier: str
    points: int
    reason: str | None = None


class RewardItemResponse(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    cost_points: int
    delivery_type: str
    reward_type: str
    reward_value: str
    duration_days: int | None = None
    is_active: bool


class RewardClaimResponse(BaseModel):
    id: int
    steam_id: str
    reward_code: str
    reward_name: str
    claim_code: str
    status: str
    points_spent: int
    claimed_at: str
    delivered_at: str | None = None
    delivered_by: str | None = None
    notes: str | None = None


class RewardClaimDeliveryInfo(BaseModel):
    delivery_type: str
    instructions: str | None = None
    membership_result: dict[str, Any] | None = None
    role_result: dict[str, Any] | None = None

class RewardClaimResultResponse(BaseModel):
    ok: bool
    claim_code: str
    reward_code: str
    reward_name: str
    cost_points: int
    remaining_points: int
    status: str
    delivery: RewardClaimDeliveryInfo


class PlayerResponse(BaseModel):
    steam_id: str
    in_game_name: str | None = None
    discord_id: str | None = None
    role: str = "PLAYER"
    roles: list[str] = Field(default_factory=list)
    active_memberships: list[dict[str, Any]] = Field(default_factory=list)
    observations: str | None = None
    is_banned: bool = False
    reward_points: int = 0
    created_at: str | None = None
    updated_at: str | None = None

class PlayerRewardBalanceResponse(BaseModel):
    steam_id: str
    discord_id: str | None = None
    in_game_name: str | None = None
    reward_points: int
    total_seeding_minutes: int
    next_point_minutes_left: int | None = None
    active_claims: list[RewardClaimResponse] = Field(default_factory=list)

