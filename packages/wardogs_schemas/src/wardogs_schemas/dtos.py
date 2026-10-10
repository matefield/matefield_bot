from __future__ import annotations
from typing import Optional, List, Any, Dict, Literal, Annotated
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
    discord_id: Optional[str] = None
    custom_welcome_message: Optional[str] = None
    observations: Optional[str] = None


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
    actor_id: Optional[DiscordSnowflake] = None
    source: Optional[Literal["DISCORD"]] = None
    operation_id: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_discord_operation(self):
        if self.source == "DISCORD" and not self.operation_id:
            raise ValueError("operation_id is required for Discord membership creation")
        return self


class MembershipStateContext(BaseModel):
    """A factual period snapshot; the API owns status and the bot formats it."""
    id: DatabaseId
    steam_id: str
    type: str
    type_name: Optional[str] = None
    discord_id: Optional[DiscordSnowflake] = None
    status: Literal["ACTIVE", "SCHEDULED", "NOT_STARTED", "ACTIVATION_PENDING", "EXPIRED", "REMOVED", "INACTIVE"]
    start_date: datetime
    end_date: Optional[datetime] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[DiscordSnowflake] = None


class CreatedMembershipItem(BaseModel):
    id: int
    steam_id: str
    type: str
    type_name: Optional[str] = None
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
    delivery: Optional[MembershipRenewalRoleDelivery] = None


class RetryMembershipRequest(BaseModel):
    guild_id: DiscordSnowflake
    actor_id: DiscordSnowflake


class RenewMembershipRequest(BaseModel):
    steam_id: str = Field(strict=True, pattern=r"^[0-9]{17}$")
    membership_type: str = Field(strict=True, min_length=1, max_length=100)
    days: Optional[int] = Field(default=None, strict=True, ge=0, le=3652)
    operation_id: str = Field(strict=True, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    guild_id: DiscordSnowflake
    actor_id: DiscordSnowflake


class RenewMembershipResponse(AddMembershipResponse):
    status: Literal["SCHEDULED"] = "SCHEDULED"
    previous_membership_id: DatabaseId


class MembershipRenewalRoleDelivery(BaseModel):
    id: DatabaseId
    membership_id: DatabaseId
    previous_membership_id: Optional[DatabaseId] = None
    steam_id: str = Field(strict=True, pattern=r"^[0-9]{17}$")
    user_id: DiscordSnowflake
    guild_id: DiscordSnowflake
    role_ids_to_add: List[DiscordSnowflake]
    role_ids_to_remove: List[DiscordSnowflake]


class MembershipRenewalDeliveriesResponse(BaseModel):
    deliveries: List[MembershipRenewalRoleDelivery]


class CompleteMembershipRenewalRequest(BaseModel):
    guild_id: DiscordSnowflake
    user_id: Optional[DiscordSnowflake] = None


class CompleteMembershipRenewalResponse(BaseModel):
    ok: Literal[True] = True
    id: DatabaseId


class RemoveMembershipRequest(BaseModel):
    operation_id: str = Field(strict=True, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    guild_id: DiscordSnowflake
    actor_id: DiscordSnowflake


class RemoveMembershipResponse(BaseModel):
    ok: Literal[True] = True
    steam_id: str
    operation_id: str
    removed_membership_ids: List[DatabaseId]
    memberships: List[MembershipStateContext] = Field(default_factory=list)
    discord: MembershipDiscordDelivery
    warcon: MembershipWarconDelivery
    replayed: bool = False


class CompleteMembershipRemovalRequest(BaseModel):
    guild_id: DiscordSnowflake
    actor_id: DiscordSnowflake


class CompleteMembershipRemovalResponse(BaseModel):
    ok: Literal[True] = True
    operation_id: str


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
    discord_role_id: Optional[str] = None



class CreateRconServerRequest(BaseModel):
    ip: str
    port: int
    password: str
    name: Optional[str] = None
    scheme: str = "http"
    is_active: bool = True
    is_default: bool = False


class UpdateRconServerRequest(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    password: Optional[str] = None
    scheme: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


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
    description: Optional[str] = None
    price_usd: float = 0.0
    price_ars: Optional[float] = None
    billing_type: str = "ONE_TIME"
    default_days: int = 30
    max_quota: Optional[int] = None
    current_usage: int = 0
    discord_role_id: Optional[str] = None
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    server_id: Optional[int] = None
    server_name: Optional[str] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MembershipTypeActionResponse(BaseModel):
    ok: bool
    message: str
    membership_type: Optional[MembershipTypeItem] = None


class RconServerItem(BaseModel):
    id: int
    name: str
    ip: str
    port: int
    scheme: str = "http"
    base_url: str
    is_active: bool = True
    is_default: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    is_online: Optional[bool] = None
    current_map: Optional[str] = None
    player_count: Optional[int] = None
    max_players: Optional[int] = None
    ping_ms: Optional[float] = None


class RconServerActionResponse(BaseModel):
    ok: bool
    message: str
    server: Optional[RconServerItem] = None


class RconServerTestResponse(BaseModel):
    ok: bool
    is_online: bool
    latency_ms: Optional[float] = None
    server_id: int
    name: str
    server_name: Optional[str] = None
    current_map: Optional[str] = None
    player_count: Optional[int] = None
    max_players: Optional[int] = None
    match_seconds: Optional[int] = None
    error: Optional[str] = None


class RconServerSyncResultItem(BaseModel):
    server_id: int
    server_name: str
    base_url: str
    status: str
    vip_slots_synced: int = 0
    bans_synced: int = 0
    error: Optional[str] = None


class RconServersSyncAllResponse(BaseModel):
    ok: bool
    message: str
    results: List[RconServerSyncResultItem] = Field(default_factory=list)


class ExportMembershipsResponse(BaseModel):
    ok: bool
    filename: str
    total_records: int
    size_bytes: int
    download_url: str
    expires_in_seconds: int = 1800


# ---------------------------------------------------------
# Rewards Schemas
# ---------------------------------------------------------

class CreateRewardItemRequest(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    cost_points: int = Field(default=1, ge=1)
    delivery_type: str = Field(default="AUTOMATIC") # AUTOMATIC or MANUAL_TICKET
    reward_type: str = Field(default="MEMBERSHIP")  # MEMBERSHIP, ROLE, CUSTOM
    reward_value: str = Field(default="")
    duration_days: Optional[int] = None
    is_active: bool = True


class ClaimRewardRequest(BaseModel):
    player_identifier: str
    reward_code: str


class DeliverClaimRequest(BaseModel):
    delivered_by: str
    notes: Optional[str] = None


class RefundClaimRequest(BaseModel):
    refunded_by: str
    reason: Optional[str] = None


class GiveRewardPointsRequest(BaseModel):
    player_identifier: str
    points: int
    reason: Optional[str] = None


class RewardItemResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    cost_points: int
    delivery_type: str
    reward_type: str
    reward_value: str
    duration_days: Optional[int] = None
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
    delivered_at: Optional[str] = None
    delivered_by: Optional[str] = None
    notes: Optional[str] = None


class PlayerRewardBalanceResponse(BaseModel):
    steam_id: str
    discord_id: Optional[str] = None
    in_game_name: Optional[str] = None
    reward_points: int
    total_seeding_minutes: int
    active_claims: List[RewardClaimResponse] = Field(default_factory=list)

