from __future__ import annotations
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlmodel import select, func, col, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import HTTPException

from src.connections.databases.db import MembershipType, Membership, RconServer, Role
from src.modules.v1.schemas.dtos import (
    CreateMembershipTypeRequest,
    UpdateMembershipTypeRequest,
    MembershipTypeItem,
)


def _price_cents(value: float) -> int:
    """Convert currency units without losing cents to binary float rounding."""
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class MembershipTypesService:

    @staticmethod
    async def list_types(session: AsyncSession, active_only: bool = False) -> List[Dict[str, Any]]:
        # Ensure default types exist if table is fresh
        await MembershipTypesService._ensure_defaults(session)

        stmt = select(MembershipType)
        if active_only:
            stmt = stmt.where(MembershipType.is_active == True)
        stmt = stmt.order_by(col(MembershipType.id))

        types = (await session.exec(stmt)).all()

        # Calculate current usage per membership type
        usage_stmt = (
            select(Membership.membership_type, func.count(col(Membership.id)))
            .where(Membership.is_active == True,
                   or_(Membership.end_time == None, Membership.end_time > datetime.now(timezone.utc)))
            .group_by(Membership.membership_type)
        )
        usage_rows = (await session.exec(usage_stmt)).all()
        usage_map: Dict[str, int] = {}
        for m_type, count in usage_rows:
            if m_type:
                u = m_type.upper()
                usage_map[u] = count
                usage_map[u.replace(" ", "_")] = count
                usage_map[u.replace("_", " ")] = count

        # Resolve server names
        server_ids = [t.server_id for t in types if t.server_id is not None]
        server_names: Dict[int, str] = {}
        if server_ids:
            servers_stmt = select(RconServer).where(col(RconServer.id).in_(server_ids))
            servers = (await session.exec(servers_stmt)).all()
            server_names = {s.id: s.name for s in servers if s.id is not None}

        # Resolve role names and discord_role_ids
        role_ids = [t.role_id for t in types if t.role_id is not None]
        role_names: Dict[int, str] = {}
        role_discord_ids: Dict[int, str] = {}
        if role_ids:
            roles_stmt = select(Role).where(col(Role.id).in_(role_ids))
            roles = (await session.exec(roles_stmt)).all()
            role_names = {r.id: r.name for r in roles if r.id is not None}
            role_discord_ids = {r.id: r.discord_role_id for r in roles if r.id is not None and r.discord_role_id}

        result = []
        for t in types:
            code_upper = t.code.upper()
            result.append({
                "id": t.id,
                "code": t.code,
                "name": t.name,
                "description": t.description,
                "price_usd": round(t.price_usd / 100.0, 2),
                "price_ars": round(t.price_ars / 100.0, 2) if t.price_ars is not None else None,
                "billing_type": t.billing_type,
                "default_days": t.default_days,
                "max_quota": t.max_quota,
                "current_usage": usage_map.get(code_upper, 0),
                "discord_role_id": role_discord_ids.get(t.role_id) if t.role_id else None,
                "role_id": t.role_id,
                "role_name": role_names.get(t.role_id),
                "server_id": t.server_id,
                "server_name": server_names.get(t.server_id) if t.server_id else "Global (Todos)",
                "is_active": t.is_active,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            })
        return result

    @staticmethod
    async def get_type(identifier: Union[int, str], session: AsyncSession) -> Optional[MembershipType]:
        if isinstance(identifier, int):
            return await session.get(MembershipType, identifier) if 0 < identifier < 2 ** 31 else None
        if isinstance(identifier, str) and len(identifier) <= 10 and identifier.isascii() and identifier.isdigit():
            type_id = int(identifier)
            if 0 < type_id < 2 ** 31:
                return await session.get(MembershipType, type_id)
        code = str(identifier).strip().upper()
        stmt = select(MembershipType).where(func.upper(MembershipType.code) == code)
        return (await session.exec(stmt)).first()

    @staticmethod
    async def create_type(req: CreateMembershipTypeRequest, session: AsyncSession) -> Dict[str, Any]:
        normalized_code = req.code.strip().upper()

        existing = (await session.exec(
            select(MembershipType).where(func.upper(MembershipType.code) == normalized_code)
        )).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Ya existe un tipo de membresía con el código '{normalized_code}'")

        if req.server_id is not None:
            server = await session.get(RconServer, req.server_id)
            if not server:
                raise HTTPException(status_code=404, detail=f"Servidor RCON con ID {req.server_id} no encontrado")

        role_to_link_id = req.role_id
        if req.discord_role_id and not role_to_link_id:
            dr_str = str(req.discord_role_id).strip()
            existing_role = (await session.exec(select(Role).where(Role.discord_role_id == dr_str))).first()
            if existing_role:
                role_to_link_id = existing_role.id
            else:
                new_role = Role(
                    code=f"ROLE_{dr_str}",
                    name=req.name.strip(),
                    discord_role_id=dr_str,
                    role_type="VIP"
                )
                session.add(new_role)
                await session.flush()
                role_to_link_id = new_role.id

        role_obj = None
        if role_to_link_id is not None:
            role_obj = await session.get(Role, role_to_link_id)
            if not role_obj:
                raise HTTPException(status_code=404, detail=f"Rol con ID {role_to_link_id} no encontrado")

        billing_type = req.billing_type.upper() if req.billing_type else "ONE_TIME"
        if billing_type not in ("ONE_TIME", "RECURRING"):
            raise HTTPException(status_code=400, detail="billing_type debe ser 'ONE_TIME' o 'RECURRING'")

        price_usd_cents = _price_cents(req.price_usd)

        now = datetime.now(timezone.utc)
        m_type = MembershipType(
            code=normalized_code,
            name=req.name.strip(),
            description=req.description,
            price_usd=price_usd_cents,
            price_ars=_price_cents(req.price_ars) if req.price_ars is not None else None,
            billing_type=billing_type,
            default_days=req.default_days if req.default_days is not None else 30,
            max_quota=req.max_quota,
            role_id=role_to_link_id,
            server_id=req.server_id,
            is_active=req.is_active,
            created_at=now,
            updated_at=now,
        )
        session.add(m_type)
        await session.commit()
        await session.refresh(m_type)

        return {
            "ok": True,
            "message": f"Tipo de membresía '{m_type.name}' creado exitosamente",
            "membership_type": {
                "id": m_type.id,
                "code": m_type.code,
                "name": m_type.name,
                "description": m_type.description,
                "price_usd": round(m_type.price_usd / 100.0, 2),
                "price_ars": round(m_type.price_ars / 100.0, 2) if m_type.price_ars is not None else None,
                "billing_type": m_type.billing_type,
                "default_days": m_type.default_days,
                "max_quota": m_type.max_quota,
                "current_usage": 0,
                "discord_role_id": role_obj.discord_role_id if role_obj else None,
                "role_id": m_type.role_id,
                "role_name": role_obj.name if role_obj else None,
                "server_id": m_type.server_id,
                "is_active": m_type.is_active,
                "created_at": m_type.created_at.isoformat() if m_type.created_at else None,
                "updated_at": m_type.updated_at.isoformat() if m_type.updated_at else None,
            }
        }

    @staticmethod
    async def update_type(type_id: int, req: UpdateMembershipTypeRequest, session: AsyncSession) -> Dict[str, Any]:
        m_type = await session.get(MembershipType, type_id)
        if not m_type:
            raise HTTPException(status_code=404, detail="Tipo de membresía no encontrado")

        if req.server_id is not None:
            server = await session.get(RconServer, req.server_id)
            if not server:
                raise HTTPException(status_code=404, detail=f"Servidor RCON con ID {req.server_id} no encontrado")
            m_type.server_id = req.server_id
        elif req.server_id is None and "server_id" in req.model_fields_set:
            m_type.server_id = None

        if "role_id" in req.model_fields_set or "discord_role_id" in req.model_fields_set:
            new_role_id = req.role_id
            if req.discord_role_id and not new_role_id:
                dr_str = str(req.discord_role_id).strip()
                existing_role = (await session.exec(select(Role).where(Role.discord_role_id == dr_str))).first()
                if existing_role:
                    new_role_id = existing_role.id
                else:
                    new_role = Role(
                        code=f"ROLE_{dr_str}",
                        name=m_type.name,
                        discord_role_id=dr_str,
                        role_type="VIP"
                    )
                    session.add(new_role)
                    await session.flush()
                    new_role_id = new_role.id
            if new_role_id is not None:
                role = await session.get(Role, new_role_id)
                if not role:
                    raise HTTPException(status_code=404, detail=f"Rol con ID {new_role_id} no encontrado")
                m_type.role_id = new_role_id
            elif "role_id" in req.model_fields_set and req.role_id is None:
                m_type.role_id = None

        if req.name is not None:
            m_type.name = req.name.strip()
        if req.description is not None:
            m_type.description = req.description
        if req.price_usd is not None:
            m_type.price_usd = _price_cents(req.price_usd)
        if "price_ars" in req.model_fields_set:
            m_type.price_ars = _price_cents(req.price_ars) if req.price_ars is not None else None
        if req.billing_type is not None:
            b_type = req.billing_type.upper()
            if b_type not in ("ONE_TIME", "RECURRING"):
                raise HTTPException(status_code=400, detail="billing_type debe ser 'ONE_TIME' o 'RECURRING'")
            m_type.billing_type = b_type
        if req.default_days is not None:
            m_type.default_days = req.default_days
        if "max_quota" in req.model_fields_set:
            m_type.max_quota = req.max_quota
        if req.is_active is not None:
            m_type.is_active = req.is_active

        m_type.updated_at = datetime.now(timezone.utc)
        session.add(m_type)
        await session.commit()
        await session.refresh(m_type)

        linked_role = await session.get(Role, m_type.role_id) if m_type.role_id else None

        return {
            "ok": True,
            "message": f"Tipo de membresía '{m_type.name}' actualizado exitosamente",
            "membership_type": {
                "id": m_type.id,
                "code": m_type.code,
                "name": m_type.name,
                "description": m_type.description,
                "price_usd": round(m_type.price_usd / 100.0, 2),
                "price_ars": round(m_type.price_ars / 100.0, 2) if m_type.price_ars is not None else None,
                "billing_type": m_type.billing_type,
                "default_days": m_type.default_days,
                "max_quota": m_type.max_quota,
                "discord_role_id": linked_role.discord_role_id if linked_role else None,
                "role_id": m_type.role_id,
                "role_name": linked_role.name if linked_role else None,
                "server_id": m_type.server_id,
                "is_active": m_type.is_active,
                "created_at": m_type.created_at.isoformat() if m_type.created_at else None,
                "updated_at": m_type.updated_at.isoformat() if m_type.updated_at else None,
            }
        }

    @staticmethod
    async def delete_type(type_id: int, session: AsyncSession) -> Dict[str, Any]:
        m_type = await session.get(MembershipType, type_id)
        if not m_type:
            raise HTTPException(status_code=404, detail="Tipo de membresía no encontrado")

        # Soft delete
        m_type.is_active = False
        m_type.updated_at = datetime.now(timezone.utc)
        session.add(m_type)
        await session.commit()

        return {"ok": True, "message": f"Tipo de membresía '{m_type.name}' desactivado"}

    @staticmethod
    async def _ensure_defaults(session: AsyncSession) -> None:
        """Seeds initial default types if the membership_types table is empty, or updates links."""
        count = (await session.exec(select(func.count(col(MembershipType.id))))).one()
        all_roles = (await session.exec(select(Role))).all()
        roles_by_code = {r.code.upper(): r.id for r in all_roles if r.code}

        if count == 0:
            defaults = [
                ("VIP_COMUN", "VIP NORMAL", "Prioridad de conexión y rol VIP por 30 días", 5.0, 7000.0, 30, roles_by_code.get("VIP_COMUN") or roles_by_code.get("VIP")),
                ("VIP_EXPRESS", "VIP EXPRESS", "Prioridad de conexión y rol VIP EXPRESS por 14 días", 3.0, 5000.0, 14, roles_by_code.get("VIP_EXPRESS")),
                ("VIP_PERMANENTE", "VIP Permanente", "Membresía vitalicia sin expiración", 0.0, None, 0, roles_by_code.get("VIP_PERMANENTE")),
            ]

            now = datetime.now(timezone.utc)
            for code, name, desc, price, price_ars, days, r_id in defaults:
                session.add(MembershipType(
                    code=code,
                    name=name,
                    description=desc,
                    price_usd=_price_cents(price),
                    price_ars=_price_cents(price_ars) if price_ars is not None else None,
                    billing_type="ONE_TIME",
                    default_days=days,
                    max_quota=None,
                    role_id=r_id,
                    server_id=None,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ))
            await session.commit()
        else:
            all_types = (await session.exec(select(MembershipType))).all()
            updated = False
            for m in all_types:
                if m.code == "VIP_COMUN":
                    if not m.role_id and (roles_by_code.get("VIP_COMUN") or roles_by_code.get("VIP")):
                        m.role_id = roles_by_code.get("VIP_COMUN") or roles_by_code.get("VIP")
                        updated = True
                elif m.code == "VIP_EXPRESS":
                    if not m.role_id and roles_by_code.get("VIP_EXPRESS"):
                        m.role_id = roles_by_code.get("VIP_EXPRESS")
                        updated = True
                elif m.code == "VIP_PERMANENTE":
                    if not m.role_id and roles_by_code.get("VIP_PERMANENTE"):
                        m.role_id = roles_by_code.get("VIP_PERMANENTE")
                        updated = True
            if updated:
                await session.commit()
