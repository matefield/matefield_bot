from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import get_session
from src.modules.v1.schemas.dtos import (
    ClaimRewardRequest,
    CreateRewardItemRequest,
    DeliverClaimRequest,
    GiveRewardPointsRequest,
    RefundClaimRequest,
)
from src.modules.v1.services.rewards_service import RewardsService
from src.security.guard import verify_api_key_guard

router = APIRouter(prefix="/rewards", tags=["Rewards & Seeding"])


@router.get("/catalog", dependencies=[Depends(verify_api_key_guard)])
async def get_rewards_catalog(
    only_active: bool = True, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    return await RewardsService.get_catalog(session, only_active=only_active)


@router.get("/balance/{identifier}", dependencies=[Depends(verify_api_key_guard)])
async def get_player_balance(
    identifier: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await RewardsService.get_player_balance(identifier, session)


@router.post("/claim", dependencies=[Depends(verify_api_key_guard)])
async def claim_reward(
    req: ClaimRewardRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await RewardsService.claim_reward(req, session)


@router.post("/admin/create", dependencies=[Depends(verify_api_key_guard)])
async def create_or_update_reward_item(
    req: CreateRewardItemRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await RewardsService.create_or_update_reward_item(req, session)


@router.get("/admin/verify/{claim_code}", dependencies=[Depends(verify_api_key_guard)])
async def verify_claim(
    claim_code: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await RewardsService.verify_claim(claim_code, session)


@router.post("/admin/deliver/{claim_code}", dependencies=[Depends(verify_api_key_guard)])
async def deliver_claim(
    claim_code: str,
    req: DeliverClaimRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await RewardsService.deliver_claim(claim_code, req, session)


@router.post("/admin/refund/{claim_code}", dependencies=[Depends(verify_api_key_guard)])
async def refund_claim(
    claim_code: str,
    req: RefundClaimRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await RewardsService.refund_claim(claim_code, req, session)


@router.post("/admin/give_points", dependencies=[Depends(verify_api_key_guard)])
async def give_points(
    req: GiveRewardPointsRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await RewardsService.give_points(req, session)
