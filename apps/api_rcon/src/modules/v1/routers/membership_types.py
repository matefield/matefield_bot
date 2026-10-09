from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlmodel.ext.asyncio.session import AsyncSession

from src.security.guard import verify_api_key_guard
from src.connections.databases.db import get_session, Role
from src.modules.v1.schemas.dtos import (
    CreateMembershipTypeRequest,
    UpdateMembershipTypeRequest,
)
from src.modules.v1.services.membership_types_service import MembershipTypesService

router = APIRouter(prefix="/membership-types", tags=["Membership Types"])


@router.get("", dependencies=[Depends(verify_api_key_guard)])
async def list_membership_types(
    active_only: bool = False,
    session: AsyncSession = Depends(get_session)
) -> List[Dict[str, Any]]:
    return await MembershipTypesService.list_types(session, active_only=active_only)


@router.post("", dependencies=[Depends(verify_api_key_guard)])
async def create_membership_type(
    req: CreateMembershipTypeRequest,
    session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    return await MembershipTypesService.create_type(req, session)


@router.get("/{identifier}", dependencies=[Depends(verify_api_key_guard)])
async def get_membership_type(
    identifier: str,
    session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    m_type = await MembershipTypesService.get_type(identifier, session)
    if not m_type:
        raise HTTPException(status_code=404, detail="Tipo de membresía no encontrado")
    role_obj = await session.get(Role, m_type.role_id) if m_type.role_id else None
    return {
        "id": m_type.id,
        "code": m_type.code,
        "name": m_type.name,
        "description": m_type.description,
        "price_usd": round(m_type.price_usd / 100.0, 2),
        "price_ars": round(m_type.price_ars / 100.0, 2) if m_type.price_ars is not None else None,
        "billing_type": m_type.billing_type,
        "default_days": m_type.default_days,
        "max_quota": m_type.max_quota,
        "discord_role_id": role_obj.discord_role_id if role_obj else None,
        "role_id": m_type.role_id,
        "role_name": role_obj.name if role_obj else None,
        "server_id": m_type.server_id,
        "is_active": m_type.is_active,
        "created_at": m_type.created_at.isoformat() if m_type.created_at else None,
        "updated_at": m_type.updated_at.isoformat() if m_type.updated_at else None,
    }


@router.put("/{type_id}", dependencies=[Depends(verify_api_key_guard)])
async def update_membership_type(
    type_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)],
    req: UpdateMembershipTypeRequest,
    session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    return await MembershipTypesService.update_type(type_id, req, session)


@router.delete("/{type_id}", dependencies=[Depends(verify_api_key_guard)])
async def delete_membership_type(
    type_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)],
    session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    return await MembershipTypesService.delete_type(type_id, session)
