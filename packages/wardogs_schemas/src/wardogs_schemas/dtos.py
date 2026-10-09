from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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
    days: int | None = None
    special_role: str | None = None
    special_role_id: int | None = None
    role_granted_id: int | None = None
    is_booster: bool | None = False
    server_id: int | None = None
    payment_source: str | None = "MANUAL"


class EditMembershipRequest(BaseModel):
    days: int | None = None
    add_days: int | None = None
    membership_type: str | None = None
    is_active: bool | None = None
    is_booster: bool | None = None
    server_id: int | None = None


class CompensateRequest(BaseModel):
    days: int


class SetBotConfigRequest(BaseModel):
    key: str
    value: str


class QuotaUpdateRequest(BaseModel):
    max_quota: int | None


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
    code: str
    name: str
    description: str | None = None
    price_usd: float = 0.0          # Precio
    billing_type: str = "ONE_TIME"  # "ONE_TIME" or "RECURRING"
    default_days: int = 30          # 0 = permanente
    max_quota: int | None = None # None = ilimitado
    discord_role_id: str | None = None
    role_id: int | None = None
    server_id: int | None = None
    is_active: bool = True


class UpdateMembershipTypeRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price_usd: float | None = None
    billing_type: str | None = None
    default_days: int | None = None
    max_quota: int | None = None
    discord_role_id: str | None = None
    role_id: int | None = None
    server_id: int | None = None
    is_active: bool | None = None


# ---------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------

class MembershipTypeItem(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    price_usd: float = 0.0
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

