import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from sqlmodel import select, func, col, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import (
    Player, PlayerSession, RewardItem, RewardClaim, BotConfig
)
from src.modules.v1.schemas.dtos import (
    CreateRewardItemRequest,
    ClaimRewardRequest,
    DeliverClaimRequest,
    RefundClaimRequest,
    GiveRewardPointsRequest,
    AddMembershipRequest,
)
from src.modules.v1.services.memberships_service import MembershipsService
from src.modules.v1.services.roles_service import RolesService

STEAM_ID_64_LENGTH = 17


class RewardsService:
    @staticmethod
    def generate_voucher_code() -> str:
        """Generates a human-friendly voucher code format: MF-XXXX-XXXX"""
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(2).upper()
        return f"MF-{part1}-{part2}"

    @staticmethod
    async def _ensure_defaults(session: AsyncSession) -> None:
        """Ensure standard initial rewards exist in catalog if table is empty."""
        defaults = [
            RewardItem(
                code="VIP_SEED",
                name="Membresía VIP Seeder (15 Días)",
                description="Acceso VIP automático por 15 días por apoyo en seeding",
                cost_points=30,
                delivery_type="AUTOMATIC",
                reward_type="MEMBERSHIP",
                reward_value="VIP_SEED",
                duration_days=15,
                is_active=True,
            ),
            RewardItem(
                code="VIP_MONTH",
                name="Membresía VIP (30 Días)",
                description="Acceso VIP automático acumulable por 30 días",
                cost_points=60,
                delivery_type="AUTOMATIC",
                reward_type="MEMBERSHIP",
                reward_value="VIP",
                duration_days=30,
                is_active=True,
            ),
            RewardItem(
                code="STEAM_GAME_KEY",
                name="Key de Juego Steam (Ticket)",
                description="Canjea en ticket de soporte por una clave de activación de Steam",
                cost_points=120,
                delivery_type="MANUAL_TICKET",
                reward_type="CUSTOM",
                reward_value="STEAM_GAME",
                duration_days=None,
                is_active=True,
            ),
        ]
        added = False
        for d in defaults:
            existing = (await session.exec(select(RewardItem).where(RewardItem.code == d.code))).first()
            if not existing:
                session.add(d)
                added = True
        if added:
            await session.commit()

    @staticmethod
    async def find_player(identifier: str, session: AsyncSession, for_update: bool = False) -> Optional[Player]:
        clean_id = identifier.strip()
        stmt = select(Player).where(or_(Player.steam_id == clean_id, Player.discord_id == clean_id))
        if for_update:
            stmt = stmt.with_for_update()
        return (await session.exec(stmt)).first()

    @staticmethod
    def evaluate_global_seeding(
        player_obj: Player,
        minutes_per_point: int,
        require_linked: bool = True,
    ) -> int:
        """
        Evaluates the global unrewarded seeding seconds of a player and awards points.
        Rewards strictly require a linked account (discord_id present).
        Returns the number of points awarded in this evaluation.
        """
        if require_linked and not player_obj.discord_id:
            return 0

        required_seconds = max(1, minutes_per_point) * 60
        unrewarded_seconds = player_obj.global_seeding_seconds - player_obj.global_rewarded_seconds

        if unrewarded_seconds >= required_seconds:
            points = unrewarded_seconds // required_seconds
            player_obj.reward_points = Player.reward_points + points
            player_obj.global_rewarded_seconds += points * required_seconds
            return points

        return 0

    @staticmethod
    async def get_catalog(session: AsyncSession, only_active: bool = True) -> List[Dict[str, Any]]:
        await RewardsService._ensure_defaults(session)
        stmt = select(RewardItem)
        if only_active:
            stmt = stmt.where(RewardItem.is_active == True)
        stmt = stmt.order_by(col(RewardItem.cost_points).asc())
        items = (await session.exec(stmt)).all()
        return [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "description": item.description,
                "cost_points": item.cost_points,
                "delivery_type": item.delivery_type,
                "reward_type": item.reward_type,
                "reward_value": item.reward_value,
                "duration_days": item.duration_days,
                "is_active": item.is_active,
            }
            for item in items
        ]

    @staticmethod
    async def create_or_update_reward_item(
        req: CreateRewardItemRequest, session: AsyncSession
    ) -> Dict[str, Any]:
        if req.cost_points <= 0:
            raise HTTPException(status_code=400, detail="El costo en puntos debe ser mayor a 0.")
        if req.duration_days is not None and req.duration_days < 0:
            raise HTTPException(status_code=400, detail="La duración en días no puede ser negativa.")

        normalized_code = req.code.strip().upper()
        existing = (await session.exec(select(RewardItem).where(RewardItem.code == normalized_code))).first()
        if existing:
            existing.name = req.name.strip()
            existing.description = req.description
            existing.cost_points = req.cost_points
            existing.delivery_type = req.delivery_type.strip().upper()
            existing.reward_type = req.reward_type.strip().upper()
            existing.reward_value = req.reward_value.strip()
            existing.duration_days = req.duration_days
            existing.is_active = req.is_active
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
            await session.commit()
            return {"ok": True, "message": f"Recompensa '{normalized_code}' actualizada exitosamente"}

        new_item = RewardItem(
            code=normalized_code,
            name=req.name.strip(),
            description=req.description,
            cost_points=req.cost_points,
            delivery_type=req.delivery_type.strip().upper(),
            reward_type=req.reward_type.strip().upper(),
            reward_value=req.reward_value.strip(),
            duration_days=req.duration_days,
            is_active=req.is_active,
        )
        session.add(new_item)
        await session.commit()
        return {"ok": True, "message": f"Recompensa '{normalized_code}' creada exitosamente"}

    @staticmethod
    async def get_player_balance(identifier: str, session: AsyncSession) -> Dict[str, Any]:
        player = await RewardsService.find_player(identifier, session)
        if not player:
            raise HTTPException(
                status_code=404,
                detail=f"Jugador con identificador '{identifier}' no encontrado. Si usas Discord ID, vincula tu cuenta primero con /player link.",
            )
        if not player.discord_id:
            raise HTTPException(
                status_code=400,
                detail=f"El jugador '{player.steam_id}' no tiene su cuenta de Discord vinculada. Es obligatorio vincularla con /player link para participar en el sistema de recompensas.",
            )

        # Calculate total seeding minutes
        total_seeding_minutes = int(player.global_seeding_seconds) // 60
        unrewarded_seconds = player.global_seeding_seconds - player.global_rewarded_seconds
            
        cfg = await session.get(BotConfig, "SEEDING_MINUTES_PER_POINT")
        minutes_per_point = int(cfg.config_value) if (cfg and cfg.config_value and cfg.config_value.isdigit()) else 30
        
        seconds_until_next = (minutes_per_point * 60) - unrewarded_seconds
        next_point_minutes_left = max(0, seconds_until_next) // 60

        # Fetch claims
        claims_stmt = (
            select(RewardClaim)
            .where(RewardClaim.steam_id == player.steam_id)
            .order_by(col(RewardClaim.claimed_at).desc())
        )
        claims = (await session.exec(claims_stmt)).all()

        # Batch-load reward items to avoid N+1 queries
        reward_ids = {c.reward_id for c in claims}
        rewards_by_id: Dict[int, RewardItem] = {}
        if reward_ids:
            fetched = (await session.exec(select(RewardItem).where(col(RewardItem.id).in_(reward_ids)))).all()
            rewards_by_id = {r.id: r for r in fetched if r.id is not None}

        claims_data = []
        for c in claims:
            reward = rewards_by_id.get(c.reward_id)
            claims_data.append(
                {
                    "id": c.id,
                    "steam_id": c.steam_id,
                    "reward_code": reward.code if reward else "UNKNOWN",
                    "reward_name": reward.name if reward else "Unknown Reward",
                    "claim_code": c.claim_code,
                    "status": c.status,
                    "points_spent": c.points_spent,
                    "claimed_at": c.claimed_at.isoformat(),
                    "delivered_at": c.delivered_at.isoformat() if c.delivered_at else None,
                    "delivered_by": c.delivered_by,
                    "notes": c.notes,
                }
            )

        return {
            "steam_id": player.steam_id,
            "discord_id": player.discord_id,
            "in_game_name": player.in_game_name,
            "reward_points": player.reward_points,
            "total_seeding_minutes": total_seeding_minutes,
            "next_point_minutes_left": next_point_minutes_left,
            "claims": claims_data,
        }

    @staticmethod
    async def claim_reward(req: ClaimRewardRequest, session: AsyncSession) -> Dict[str, Any]:
        player = await RewardsService.find_player(req.player_identifier, session, for_update=True)
        if not player:
            raise HTTPException(
                status_code=404,
                detail=f"Jugador '{req.player_identifier}' no encontrado.",
            )
        if not player.discord_id:
            raise HTTPException(
                status_code=400,
                detail="Es obligatorio tener tu cuenta de Discord vinculada con Steam para poder canjear recompensas. Usa /player link primero.",
            )

        norm_code = req.reward_code.strip().upper()
        reward = (
            await session.exec(
                select(RewardItem).where(func.upper(RewardItem.code) == norm_code, RewardItem.is_active == True)
            )
        ).first()

        if not reward:
            raise HTTPException(
                status_code=404,
                detail=f"Recompensa '{norm_code}' no encontrada o inactiva en el catálogo.",
            )

        if player.reward_points < reward.cost_points:
            raise HTTPException(
                status_code=400,
                detail=f"Puntos insuficientes. Tienes {player.reward_points} pts y la recompensa cuesta {reward.cost_points} pts.",
            )

        # Generate unique claim voucher
        while True:
            code = RewardsService.generate_voucher_code()
            collision = (await session.exec(select(RewardClaim).where(RewardClaim.claim_code == code))).first()
            if not collision:
                break

        # Deduct points
        player.reward_points -= reward.cost_points
        session.add(player)

        assert reward.id is not None
        claim = RewardClaim(
            steam_id=player.steam_id,
            reward_id=reward.id,
            claim_code=code,
            status="PENDING",
            points_spent=reward.cost_points,
            claimed_at=datetime.now(timezone.utc),
        )
        session.add(claim)
        await session.flush()

        delivery_info: Dict[str, Any] = {"delivery_type": reward.delivery_type}

        # Automatic Fulfillment
        if reward.delivery_type.upper() == "AUTOMATIC":
            if reward.reward_type.upper() == "MEMBERSHIP":
                membership_req = AddMembershipRequest(
                    steam_id=player.steam_id,
                    membership_type=reward.reward_value,
                    days=reward.duration_days,
                    payment_source="REWARDS",
                )
                mem_res = await MembershipsService.add_membership(membership_req, session)
                claim.status = "DELIVERED"
                claim.delivered_at = datetime.now(timezone.utc)
                claim.delivered_by = "SYSTEM"
                claim.notes = f"Entrega automática de membresía {reward.reward_value}"
                delivery_info["membership_result"] = mem_res
            elif reward.reward_type.upper() == "ROLE":
                role_res = await RolesService.add_special_role(player.steam_id, reward.reward_value, session)
                claim.status = "DELIVERED"
                claim.delivered_at = datetime.now(timezone.utc)
                claim.delivered_by = "SYSTEM"
                claim.notes = f"Entrega automática de rol especial {reward.reward_value}"
                delivery_info["role_result"] = role_res
            else:
                claim.status = "PENDING"
                claim.notes = "Recompensa automática no reconocida, marcada como PENDING para revisión manual"

        elif reward.delivery_type.upper() == "MANUAL_TICKET":
            claim.status = "PENDING"
            claim.notes = "Pendiente de reclamo vía ticket por el usuario"
            delivery_info["instructions"] = (
                f"Abre un ticket de soporte en Discord y proporciona tu código de canje: `{code}` para recibir tu recompensa."
            )

        remaining_points = player.reward_points
        reward_code = reward.code
        reward_name = reward.name
        cost_points = reward.cost_points

        session.add(claim)
        await session.commit()
        await session.refresh(claim)

        return {
            "ok": True,
            "claim_code": claim.claim_code,
            "reward_code": reward_code,
            "reward_name": reward_name,
            "cost_points": cost_points,
            "remaining_points": remaining_points,
            "status": claim.status,
            "delivery": delivery_info,
        }

    @staticmethod
    async def verify_claim(claim_code: str, session: AsyncSession) -> Dict[str, Any]:
        clean_code = claim_code.strip().upper()
        claim = (await session.exec(select(RewardClaim).where(RewardClaim.claim_code == clean_code))).first()
        if not claim:
            raise HTTPException(status_code=404, detail=f"Código de canje '{clean_code}' no existe.")

        reward = await session.get(RewardItem, claim.reward_id)
        player = await session.get(Player, claim.steam_id)

        return {
            "claim_code": claim.claim_code,
            "status": claim.status,
            "steam_id": claim.steam_id,
            "discord_id": player.discord_id if player else None,
            "player_name": player.in_game_name if player else None,
            "reward_code": reward.code if reward else "UNKNOWN",
            "reward_name": reward.name if reward else "Unknown Reward",
            "delivery_type": reward.delivery_type if reward else "UNKNOWN",
            "points_spent": claim.points_spent,
            "claimed_at": claim.claimed_at.isoformat(),
            "delivered_at": claim.delivered_at.isoformat() if claim.delivered_at else None,
            "delivered_by": claim.delivered_by,
            "notes": claim.notes,
        }

    @staticmethod
    async def deliver_claim(
        claim_code: str, req: DeliverClaimRequest, session: AsyncSession
    ) -> Dict[str, Any]:
        clean_code = claim_code.strip().upper()
        claim = (await session.exec(select(RewardClaim).where(RewardClaim.claim_code == clean_code).with_for_update())).first()
        if not claim:
            raise HTTPException(status_code=404, detail=f"Código de canje '{clean_code}' no existe.")

        if claim.status == "DELIVERED":
            raise HTTPException(
                status_code=400,
                detail=f"El reclamo '{clean_code}' ya fue entregado previamente el {claim.delivered_at} por {claim.delivered_by}.",
            )
        if claim.status == "REFUNDED":
            raise HTTPException(
                status_code=400,
                detail=f"El reclamo '{clean_code}' fue reembolsado y no puede ser marcado como entregado.",
            )

        claim.status = "DELIVERED"
        claim.delivered_at = datetime.now(timezone.utc)
        claim.delivered_by = req.delivered_by.strip()
        if req.notes:
            claim.notes = req.notes.strip()

        session.add(claim)
        await session.commit()
        return {
            "ok": True,
            "status": "DELIVERED",
            "message": f"Reclamo '{clean_code}' marcado como entregado exitosamente por {req.delivered_by}."
        }

    @staticmethod
    async def refund_claim(
        claim_code: str, req: RefundClaimRequest, session: AsyncSession
    ) -> Dict[str, Any]:
        clean_code = claim_code.strip().upper()
        claim = (await session.exec(select(RewardClaim).where(RewardClaim.claim_code == clean_code).with_for_update())).first()
        if not claim:
            raise HTTPException(status_code=404, detail=f"Código de canje '{clean_code}' no existe.")

        if claim.status == "REFUNDED":
            raise HTTPException(status_code=400, detail=f"El reclamo '{clean_code}' ya fue reembolsado anteriormente.")

        points_refunded = claim.points_spent
        new_balance = None
        player = await session.get(Player, claim.steam_id)
        if player:
            player.reward_points += points_refunded
            new_balance = player.reward_points
            session.add(player)

        claim.status = "REFUNDED"
        claim.notes = f"Reembolsado por {req.refunded_by}. Razón: {req.reason or 'Sin motivo'}"
        session.add(claim)
        await session.commit()

        return {
            "ok": True,
            "status": "REFUNDED",
            "new_status": "REFUNDED",
            "message": f"Reclamo '{clean_code}' reembolsado con éxito. Se devolvieron {points_refunded} pts al jugador.",
            "refunded_points": points_refunded,
            "new_balance": new_balance,
        }

    @staticmethod
    async def give_points(req: GiveRewardPointsRequest, session: AsyncSession) -> Dict[str, Any]:
        player = await RewardsService.find_player(req.player_identifier, session, for_update=True)
        if not player:
            # If identifier is a 17-digit SteamID, create the player record
            clean_id = req.player_identifier.strip()
            if clean_id.isdigit() and len(clean_id) == STEAM_ID_64_LENGTH:
                player = Player(steam_id=clean_id, reward_points=0)
                session.add(player)
                await session.flush()
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Jugador '{req.player_identifier}' no encontrado.",
                )

        if req.points < 0 and (player.reward_points + req.points < 0):
            raise HTTPException(
                status_code=400,
                detail=f"Saldo de puntos insuficiente. El jugador solo tiene {player.reward_points} pts y se intentó descontar {abs(req.points)} pts.",
            )

        target_steam_id = player.steam_id
        new_balance = player.reward_points + req.points
        player.reward_points = new_balance
        session.add(player)
        await session.commit()

        return {
            "ok": True,
            "steam_id": target_steam_id,
            "points_adjusted": req.points,
            "new_balance": new_balance,
            "reason": req.reason,
        }
