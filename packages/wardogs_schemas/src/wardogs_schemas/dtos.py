from __future__ import annotations
from typing import Optional, List, Any, Dict
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
    discord_id: Optional[str] = None
    custom_welcome_message: Optional[str] = None
    observations: Optional[str] = None


class AddMembershipRequest(BaseModel):
    steam_id: str
    membership_type: str
    days: Optional[int] = None
    special_role: Optional[str] = None
    special_role_id: Optional[int] = None
    role_granted_id: Optional[int] = None
    is_booster: Optional[bool] = False
    server_id: Optional[int] = None
    payment_source: Optional[str] = "MANUAL"


class EditMembershipRequest(BaseModel):
    days: Optional[int] = None
    add_days: Optional[int] = None
    membership_type: Optional[str] = None
    is_active: Optional[bool] = None
    is_booster: Optional[bool] = None
    server_id: Optional[int] = None


class CompensateRequest(BaseModel):
    days: int


class SetBotConfigRequest(BaseModel):
    key: str
    value: str


class QuotaUpdateRequest(BaseModel):
    max_quota: Optional[int]


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
    code: str
    name: str
    description: Optional[str] = None
    price_usd: float = 0.0          # Precio
    billing_type: str = "ONE_TIME"  # "ONE_TIME" or "RECURRING"
    default_days: int = 30          # 0 = permanente
    max_quota: Optional[int] = None # None = ilimitado
    discord_role_id: Optional[str] = None
    role_id: Optional[int] = None
    server_id: Optional[int] = None
    is_active: bool = True


class UpdateMembershipTypeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_usd: Optional[float] = None
    billing_type: Optional[str] = None
    default_days: Optional[int] = None
    max_quota: Optional[int] = None
    discord_role_id: Optional[str] = None
    role_id: Optional[int] = None
    server_id: Optional[int] = None
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
    created_at: Optional[str] = None


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


class RewardClaimDeliveryInfo(BaseModel):
    delivery_type: str
    instructions: Optional[str] = None
    membership_result: Optional[Dict[str, Any]] = None
    role_result: Optional[Dict[str, Any]] = None

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
    in_game_name: Optional[str] = None
    discord_id: Optional[str] = None
    role: str = "PLAYER"
    roles: List[str] = Field(default_factory=list)
    active_memberships: List[Dict[str, Any]] = Field(default_factory=list)
    observations: Optional[str] = None
    is_banned: bool = False
    reward_points: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class PlayerRewardBalanceResponse(BaseModel):
    steam_id: str
    discord_id: Optional[str] = None
    in_game_name: Optional[str] = None
    reward_points: int
    total_seeding_minutes: int
    next_point_minutes_left: Optional[int] = None
    active_claims: List[RewardClaimResponse] = Field(default_factory=list)

