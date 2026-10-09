import csv
import io
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import (
    BotConfig,
    Match,
    MatchPlayerStats,
    MatchTeamStats,
    Membership,
    MembershipType,
    Player,
    PlayerRole,
    Role,
    Team,
)
from src.modules.v1.schemas.dtos import SetBotConfigRequest


class ConfigService:
    @staticmethod
    async def get_bot_config(key: str, session: AsyncSession) -> dict[str, Any]:
        config = await session.get(BotConfig, key)
        if not config:
            raise HTTPException(status_code=404, detail="Config key not found")
        return {"key": config.config_key, "value": config.config_value}

    @staticmethod
    async def set_bot_config(req: SetBotConfigRequest, session: AsyncSession) -> dict[str, Any]:
        config = await session.get(BotConfig, req.key)
        if not config:
            config = BotConfig(config_key=req.key, config_value=req.value)
            session.add(config)
        else:
            config.config_value = req.value
        await session.commit()
        return {"ok": True, "message": "Config updated"}

    @staticmethod
    async def delete_bot_config(key: str, session: AsyncSession) -> dict[str, Any]:
        config = await session.get(BotConfig, key)
        if config:
            await session.delete(config)
            await session.commit()
        return {"ok": True, "message": "Config deleted"}

    @staticmethod
    async def get_all_bot_configs(session: AsyncSession) -> dict[str, Any]:
        configs = (await session.exec(select(BotConfig))).all()
        return {"configs": {c.config_key: c.config_value for c in configs}}

    @staticmethod
    async def get_quotas(session: AsyncSession) -> dict[str, Any]:
        from src.modules.v1.services.membership_types_service import (
            MembershipTypesService,
        )
        await MembershipTypesService._ensure_defaults(session)

        types = (await session.exec(select(MembershipType))).all()
        usage_stmt = select(Membership.membership_type, func.count(col(Membership.id))).where(Membership.is_active == True).group_by(Membership.membership_type)
        usage = (await session.exec(usage_stmt)).all()
        usage_dict = {t.upper(): c for t, c in usage}
        
        result = []
        for c in types:
            result.append({
                "membership_type": c.code,
                "max_quota": c.max_quota,
                "current_usage": usage_dict.get(c.code.upper(), 0)
            })
            
        return {"quotas": result}

    @staticmethod
    async def update_quota(membership_type: str, max_quota: int | None, session: AsyncSession) -> dict[str, Any]:
        normalized_type = membership_type.strip().upper()
        
        # Update MembershipType
        m_type = (await session.exec(select(MembershipType).where(func.upper(MembershipType.code) == normalized_type))).first()
        if m_type:
            m_type.max_quota = max_quota
            session.add(m_type)
            await session.commit()
        else:
            raise HTTPException(status_code=404, detail=f"Tipo de membresía '{normalized_type}' no encontrado")
            
        return {"success": True, "membership_type": normalized_type, "max_quota": max_quota}

    @staticmethod
    async def export_table_csv(table_name: str, session: AsyncSession) -> StreamingResponse:
        table_map = {
            "players": Player,
            "roles": Role,
            "player_roles": PlayerRole,
            "memberships": Membership,
            "membership_types": MembershipType,
            "teams": Team,
            "matches": Match,
            "match_team_stats": MatchTeamStats,
            "match_player_stats": MatchPlayerStats
        }
        
        if table_name not in table_map:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
            
        model = table_map[table_name]
        records = (await session.exec(select(model))).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        if not records:
            headers = list(model.model_fields.keys())
            writer.writerow(headers)
        else:
            headers = list(records[0].model_dump().keys())
            writer.writerow(headers)
            for record in records:
                writer.writerow(list(record.model_dump().values()))
                
        output.seek(0)
        
        return StreamingResponse(
            output, 
            media_type="text/csv", 
            headers={"Content-Disposition": f'attachment; filename="{table_name}.csv"'}
        )
