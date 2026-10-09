from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_schemas import v1 as schemas

from src.connections.databases.db import get_session
from src.modules.v1.schemas.dtos import ConfigUpdateRequest
from src.modules.v1.services.backup_service import create_database_sql_backup
from src.modules.v1.services.server_service import ServerService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Server & RCON"])

@router.get("/status", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Status)
async def get_status(session: AsyncSession = Depends(get_session)):
    return await ServerService.get_status(session=session)

@router.get("/players", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Players1)
async def get_players(session: AsyncSession = Depends(get_session)):
    return await ServerService.get_players(session=session)

@router.get("/audit", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Audit)
async def get_audit(limit: int = 50, session: AsyncSession = Depends(get_session)):
    return await ServerService.get_audit_logs(limit, session=session)

@router.get("/reserved-slots", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.ReservedSlots)
async def get_reserved_slots(session: AsyncSession = Depends(get_session)):
    return await ServerService.get_reserved_slots(session=session)

@router.post("/reserved-slots", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def add_reserved_slot(req: schemas.Player, session: AsyncSession = Depends(get_session)):
    if not req.steamId:
        raise HTTPException(status_code=400, detail="steamId is required")
    await ServerService.add_reserved_slot(req.steamId, session=session)
    return {"ok": True}

@router.delete("/reserved-slots/{steam_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def remove_reserved_slot(steam_id: str, session: AsyncSession = Depends(get_session)):
    await ServerService.remove_reserved_slot(steam_id, session=session)
    return {"ok": True}

@router.post("/broadcast", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def broadcast(req: schemas.MessageRequest, session: AsyncSession = Depends(get_session)):
    await ServerService.broadcast(req.message, session=session)
    return {"ok": True}

@router.post("/players/{steam_id}/message", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def send_player_message(steam_id: str, req: schemas.MessageRequest, session: AsyncSession = Depends(get_session)):
    await ServerService.send_player_message(steam_id, req.message, session=session)
    return {"ok": True}

@router.post("/players/{steam_id}/kick", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def kick_player(steam_id: str, req: schemas.ReasonRequest, session: AsyncSession = Depends(get_session)):
    await ServerService.kick_player(steam_id, req.reason or "", session=session)
    return {"ok": True}

@router.post("/players/{steam_id}/faction", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def switch_faction(steam_id: str, req: schemas.FactionRequest, session: AsyncSession = Depends(get_session)):
    await ServerService.switch_faction(steam_id, req.faction, session=session)
    return {"ok": True}

@router.get("/config", dependencies=[Depends(verify_api_key_guard)])
async def get_config(session: AsyncSession = Depends(get_session)):
    """Returns the active server INI configuration text."""
    _, client = await ServerService._get_client(session)
    return await client.get_config()

@router.put("/config", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.ConfigResult)
async def update_config(req: ConfigUpdateRequest, session: AsyncSession = Depends(get_session)):
    return await ServerService.update_config(req.revision, req.new_text, session=session)

@router.post("/db/backup", dependencies=[Depends(verify_api_key_guard)])
async def trigger_database_backup(session: AsyncSession = Depends(get_session)):
    """Triggers an on-demand SQL backup of the full database."""
    file_path = await create_database_sql_backup(session)
    return {
        "ok": True,
        "message": f"Backup SQL generado exitosamente: {file_path.name}",
        "filename": file_path.name,
        "size_bytes": file_path.stat().st_size
    }
