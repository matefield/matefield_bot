from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_schemas import v1 as schemas

from src.connections.databases.db import get_session
from src.modules.v1.schemas.dtos import QuotaUpdateRequest, SetBotConfigRequest
from src.modules.v1.services.config_service import ConfigService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Config & Quotas"])

@router.get("/bot/config/{key}", dependencies=[Depends(verify_api_key_guard)])
async def get_bot_config(key: str, session: AsyncSession = Depends(get_session)):
    return await ConfigService.get_bot_config(key, session)

@router.put("/bot/config", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def set_bot_config(req: SetBotConfigRequest, session: AsyncSession = Depends(get_session)):
    return await ConfigService.set_bot_config(req, session)

@router.delete("/bot/config/{key}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def delete_bot_config(key: str, session: AsyncSession = Depends(get_session)):
    return await ConfigService.delete_bot_config(key, session)

@router.get("/bot/configs", dependencies=[Depends(verify_api_key_guard)])
async def get_all_bot_configs(session: AsyncSession = Depends(get_session)):
    return await ConfigService.get_all_bot_configs(session)

@router.get("/db/quotas", dependencies=[Depends(verify_api_key_guard)])
async def get_quotas(session: AsyncSession = Depends(get_session)):
    return await ConfigService.get_quotas(session)

@router.put("/db/quotas/{membership_type}", dependencies=[Depends(verify_api_key_guard)])
async def update_quota(membership_type: str, request: QuotaUpdateRequest, session: AsyncSession = Depends(get_session)):
    return await ConfigService.update_quota(membership_type, request.max_quota, session)

@router.get("/db/export/{table_name}", dependencies=[Depends(verify_api_key_guard)])
async def export_table_csv(table_name: str, session: AsyncSession = Depends(get_session)):
    return await ConfigService.export_table_csv(table_name, session)
