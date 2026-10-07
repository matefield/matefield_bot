"""
Database models (SQLModel / SQLAlchemy) and engine setup.

All ORM tables are defined here so that ``SQLModel.metadata.sorted_tables``
returns them in correct foreign-key dependency order for the backup service.

The async engine and ``get_session`` dependency are also exported from this
module so that routers and services have a single import point for DB access.
"""
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import Column, DateTime, BigInteger, ForeignKey, Text, CheckConstraint
from sqlalchemy.ext.asyncio import create_async_engine
from datetime import datetime, timezone
from enum import Enum
import uuid

from wardogs_config import ENVIRONMENT_SETTINGS

class RoleType(str, Enum):
    SYSTEM = "SYSTEM"
    VIP = "VIP"
    PUNISHMENT = "PUNISHMENT"
    PUBLIC = "PUBLIC"
    SPECIAL = "SPECIAL"

# --- Intermediary Tables ---

class PlayerRole(SQLModel, table=True):
    __tablename__ = "player_roles"
    steam_id: str = Field(foreign_key="players.steam_id", primary_key=True)
    role_id: int = Field(sa_column=Column(ForeignKey("roles.id"), primary_key=True))

# --- Core Entities ---

class Role(SQLModel, table=True):
    __tablename__ = "roles"
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    discord_role_id: Optional[str] = Field(default=None, index=True)
    role_type: str = Field(index=True)
    
    # Relationships
    players: List["Player"] = Relationship(back_populates="roles", link_model=PlayerRole)


class Player(SQLModel, table=True):
    __tablename__ = "players"
    steam_id: str = Field(primary_key=True)
    discord_id: Optional[str] = Field(default=None, unique=True, index=True)
    custom_welcome_message: Optional[str] = Field(default=None)
    observations: Optional[str] = Field(default=None)
    in_game_name: Optional[str] = Field(default=None)
    avatar_url: Optional[str] = Field(default=None)
    reward_points: int = Field(default=0)
    global_seeding_seconds: int = Field(default=0)
    global_rewarded_seconds: int = Field(default=0)
    
    __table_args__ = (
        CheckConstraint("reward_points >= 0", name="check_player_points_positive"),
    )
    
    # Relationships
    roles: List[Role] = Relationship(back_populates="players", link_model=PlayerRole)
    memberships: List["Membership"] = Relationship(back_populates="player")
    reward_claims: List["RewardClaim"] = Relationship(back_populates="player")


class Membership(SQLModel, table=True):
    __tablename__ = "memberships"
    id: Optional[int] = Field(default=None, primary_key=True)
    steam_id: str = Field(foreign_key="players.steam_id", index=True)
    membership_type: str = Field(index=True, sa_column_kwargs={"name": "type"})
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column("start_date", DateTime(timezone=True)))
    end_time: Optional[datetime] = Field(default=None, sa_column=Column("end_date", DateTime(timezone=True))) # Null means permanent
    is_active: bool = Field(default=True)
    is_booster: bool = Field(default=False)
    role_granted_id: Optional[int] = Field(default=None, sa_column=Column("role_granted_id", ForeignKey("roles.id")))
    special_role_id: Optional[int] = Field(default=None, sa_column=Column("special_role_id", ForeignKey("roles.id"), index=True))
    rcon_sync_status: str = Field(default="PENDING", sa_column_kwargs={"server_default": "PENDING"}) # PENDING, SUCCESS, FAILED
    server_id: Optional[int] = Field(default=None, foreign_key="rcon_servers.id")
    payment_source: str = Field(default="MANUAL", sa_column_kwargs={"server_default": "MANUAL"}) # MANUAL, REWARDS
    # Relationships
    player: Player = Relationship(back_populates="memberships")
    role_granted: Optional[Role] = Relationship(sa_relationship_kwargs={"foreign_keys": "[Membership.role_granted_id]"})
    special_role: Optional[Role] = Relationship(sa_relationship_kwargs={"foreign_keys": "[Membership.special_role_id]"})

class PlayerSession(SQLModel, table=True):
    __tablename__ = "player_sessions"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    steam_id: str = Field(foreign_key="players.steam_id", index=True)
    server_id: Optional[int] = Field(default=None, foreign_key="rcon_servers.id")
    
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    end_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    
    total_seconds: int = Field(default=0)
    seeding_seconds: int = Field(default=0)
    rewarded_seeding_seconds: int = Field(default=0)



class Team(SQLModel, table=True):
    __tablename__ = "teams"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True) # Lonestar, Manticore, Valkyre
    code: str = Field(unique=True) # BLU, GRN, RED


class Match(SQLModel, table=True):
    __tablename__ = "matches"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    map_name: str
    start_time: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    end_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    winning_team_id: Optional[int] = Field(default=None, foreign_key="teams.id")
    
    # Relationships deleted to avoid async lazy load cascades


# --- Stats Tables ---

class MatchTeamStats(SQLModel, table=True):
    __tablename__ = "match_team_stats"
    match_id: str = Field(foreign_key="matches.id", primary_key=True)
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    score: int = Field(default=0)
    
    # Relationships
    team: Team = Relationship()


class MatchPlayerStats(SQLModel, table=True):
    __tablename__ = "match_player_stats"
    steam_id: str = Field(foreign_key="players.steam_id", primary_key=True)
    match_id: str = Field(foreign_key="matches.id", primary_key=True)
    team_id: Optional[int] = Field(default=None, foreign_key="teams.id")
    squad_id: Optional[str] = Field(default=None, sa_column=Column(ForeignKey("squads.id", ondelete="SET NULL")))
    kills: int = Field(default=0)
    deaths: int = Field(default=0)
    cash_earned: int = Field(default=0)
    
    # Relationships
    player: Player = Relationship()
    team: Optional[Team] = Relationship()
    squad: Optional["Squad"] = Relationship()


class Squad(SQLModel, table=True):
    __tablename__ = "squads"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(unique=True, index=True)
    tag: str = Field(max_length=4, index=True)
    leader_steam_id: str = Field(foreign_key="players.steam_id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))
    
    total_kills: int = Field(default=0)
    total_deaths: int = Field(default=0)
    total_cash_earned: int = Field(default=0)
    total_matches_played: int = Field(default=0)
    
    # Relationships
    leader: Player = Relationship()
    members: List["SquadMember"] = Relationship(back_populates="squad")

class SquadMember(SQLModel, table=True):
    __tablename__ = "squad_members"
    squad_id: str = Field(foreign_key="squads.id", primary_key=True)
    steam_id: str = Field(foreign_key="players.steam_id", primary_key=True)
    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))
    
    squad: Squad = Relationship(back_populates="members")
    player: Player = Relationship()

class SquadInvite(SQLModel, table=True):
    __tablename__ = "squad_invites"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    squad_id: str = Field(foreign_key="squads.id", index=True)
    inviter_steam_id: str = Field(foreign_key="players.steam_id")
    invitee_discord_id: str = Field(index=True)
    status: str = Field(default="PENDING") # PENDING, ACCEPTED, REJECTED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))


class SteamLinkRedemption(SQLModel, table=True):
    __tablename__ = "steam_link_redemptions"
    token_hash: str = Field(primary_key=True)
    expires_at: int = Field(index=True)


class BotConfig(SQLModel, table=True):
    __tablename__ = "bot_config"
    config_key: str = Field(primary_key=True)
    config_value: str = Field(sa_column=Column(Text))


class MembershipType(SQLModel, table=True):
    __tablename__ = "membership_types"
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    description: Optional[str] = Field(default=None)
    price_usd: int = Field(default=0) # Stored in cents
    billing_type: str = Field(default="ONE_TIME") # "ONE_TIME" or "RECURRING"
    default_days: int = Field(default=30)         # 0 = permanente
    max_quota: Optional[int] = Field(default=None)# None = ilimitado
    role_id: Optional[int] = Field(default=None, foreign_key="roles.id", index=True)
    server_id: Optional[int] = Field(default=None, foreign_key="rcon_servers.id")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))

    # Relationships
    role: Optional[Role] = Relationship()





class RconServer(SQLModel, table=True):
    __tablename__ = "rcon_servers"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    ip: str
    port: int
    password: str
    scheme: str = Field(default="http") # "http" or "https"
    is_active: bool = Field(default=True)
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.ip}:{self.port}"


class RewardItem(SQLModel, table=True):
    __tablename__ = "reward_items"
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    description: Optional[str] = Field(default=None)
    cost_points: int = Field(default=1)
    delivery_type: str = Field(default="AUTOMATIC") # AUTOMATIC or MANUAL_TICKET
    reward_type: str = Field(default="MEMBERSHIP")  # MEMBERSHIP, ROLE, CUSTOM
    reward_value: str = Field(default="")           # Membership type code, role code, or custom item
    duration_days: Optional[int] = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))

    claims: List["RewardClaim"] = Relationship(back_populates="reward")


class RewardClaim(SQLModel, table=True):
    __tablename__ = "reward_claims"
    id: Optional[int] = Field(default=None, primary_key=True)
    steam_id: str = Field(foreign_key="players.steam_id", index=True)
    reward_id: int = Field(foreign_key="reward_items.id", index=True)
    claim_code: str = Field(unique=True, index=True)
    status: str = Field(default="PENDING", index=True) # PENDING, DELIVERED, REFUNDED
    points_spent: int = Field(default=0)
    claimed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))
    
    __table_args__ = (
        CheckConstraint("points_spent >= 0", name="check_claim_points_positive"),
    )
    
    delivered_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    delivered_by: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)

    # Relationships
    reward: Optional[RewardItem] = Relationship(back_populates="claims")
    player: Optional[Player] = Relationship(back_populates="reward_claims")


# --- Database Setup ---
# Utilizamos una configuración conservadora de pool para bases de datos compartidas (como BisectHosting)
# que suelen tener un límite bajo de conexiones (max_connections).
engine = create_async_engine(
    ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.DATABASE_URL, 
    echo=False,
    pool_size=3,          # Mantiene 3 conexiones abiertas como base
    max_overflow=2,       # Permite hasta 2 conexiones extra bajo carga (Total: 5)
    pool_timeout=30,      # Espera hasta 30s por una conexión en lugar de fallar
    pool_recycle=1800,    # Recicla conexiones cada 30 minutos
    pool_pre_ping=True,   # Verifica si la conexión está viva antes de usarla
)


async def get_session():
    """FastAPI dependency that yields an async database session."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
