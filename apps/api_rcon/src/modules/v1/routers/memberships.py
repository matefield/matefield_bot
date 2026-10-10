from typing import Annotated, Any, Dict, Optional
from fastapi import APIRouter, Depends, Request, HTTPException, Header, Path, Query
from fastapi.responses import FileResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas import v1 as schemas
from wardogs_schemas.dtos import DiscordSnowflake

from src.connections.databases.db import get_session
from src.modules.v1.schemas.dtos import (
    AddMembershipRequest, AddMembershipResponse, EditMembershipRequest, CompensateRequest,
    RemoveMembershipRequest, RemoveMembershipResponse,
    CompleteMembershipRemovalRequest, CompleteMembershipRemovalResponse,
)
from src.modules.v1.services.export_service import (
    generate_export_download_token,
    generate_memberships_csv,
    get_export_dir,
    verify_export_download_token,
)
from src.modules.v1.services.membership_removals_service import MembershipRemovalsService
from src.modules.v1.services.memberships_service import MembershipsService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Memberships"])

# TTL for the one-time CSV export download token
_EXPORT_TOKEN_TTL_SECONDS = 1800  # 30 minutes

@router.post("/db/players/membership", dependencies=[Depends(verify_api_key_guard)], response_model=AddMembershipResponse)
async def add_membership(req: AddMembershipRequest, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.add_membership(req, session)


@router.post("/db/players/{steam_id}/membership/remove", dependencies=[Depends(verify_api_key_guard)], response_model=RemoveMembershipResponse)
async def remove_player_membership(steam_id: str, req: RemoveMembershipRequest, session: AsyncSession = Depends(get_session)):
    return await MembershipRemovalsService.remove(steam_id, req, session)


@router.post("/db/players/{steam_id}/membership/remove/{operation_id}/complete", dependencies=[Depends(verify_api_key_guard)], response_model=CompleteMembershipRemovalResponse)
async def complete_membership_removal(steam_id: str, operation_id: str, req: CompleteMembershipRemovalRequest,
                                      session: AsyncSession = Depends(get_session)):
    return await MembershipRemovalsService.complete(steam_id, operation_id, req, session)

@router.put("/db/memberships/{membership_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def edit_membership(membership_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)], req: EditMembershipRequest, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.edit_membership(membership_id, req, session)

@router.post("/db/memberships/compensate", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def compensate_memberships(req: CompensateRequest, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.compensate_memberships(req.days, session)

@router.delete("/db/memberships/{membership_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def delete_membership(membership_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)], session: AsyncSession = Depends(get_session)):
    return await MembershipsService.delete_membership(membership_id, session)

@router.get("/db/memberships", dependencies=[Depends(verify_api_key_guard)])
async def get_paginated_memberships(page: Annotated[int, Query(ge=1, le=2 ** 31 - 1)] = 1,
                                    limit: Annotated[int, Query(ge=1, le=2 ** 31 - 1)] = 10,
                                    discord_id: Optional[str] = None,
                                    guild_id: Optional[DiscordSnowflake] = None,
                                    session: AsyncSession = Depends(get_session)):
    return await MembershipsService.get_paginated_memberships(page, limit, session, discord_id=discord_id, guild_id=guild_id)

@router.post("/db/sync_memberships", dependencies=[Depends(verify_api_key_guard)])
async def sync_memberships_endpoint(session: AsyncSession = Depends(get_session)):
    return await MembershipsService.sync_memberships_logic(session)

@router.get("/db/rcon_sync_status", dependencies=[Depends(verify_api_key_guard)])
async def rcon_sync_status(session: AsyncSession = Depends(get_session)):
    return await MembershipsService.get_rcon_sync_status(session)

@router.post("/db/memberships/export", dependencies=[Depends(verify_api_key_guard)])
async def export_memberships_endpoint(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Generates a CSV export and returns a short-lived authenticated download URL."""
    csv_file, filename, count = await generate_memberships_csv(session)
    token = generate_export_download_token(filename, expires_in_seconds=_EXPORT_TOKEN_TTL_SECONDS)

    public_url = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.PUBLIC_API_URL.strip()
    base_url = (public_url or str(request.base_url)).rstrip("/")
    download_url = f"{base_url}/api/v1/db/memberships/export/download/{filename}?token={token}"

    return {
        "ok": True,
        "filename": filename,
        "total_records": count,
        "size_bytes": csv_file.stat().st_size,
        "download_url": download_url,
        "expires_in_seconds": _EXPORT_TOKEN_TTL_SECONDS
    }

@router.get("/db/memberships/export/download/{filename}")
async def download_memberships_export_endpoint(
    filename: str,
    token: str | None = None,
    api_key: str | None = None,
    api_key_header: str | None = Header(None, alias="X-API-Key")
):
    master_key = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY
    is_authorized = False

    if token and verify_export_download_token(filename, token) or (api_key and api_key == master_key) or (api_key_header and api_key_header == master_key):
        is_authorized = True

    if not is_authorized:
        raise HTTPException(status_code=403, detail="Token de descarga inválido o expirado")

    export_dir = get_export_dir().resolve()
    file_path = (export_dir / filename).resolve()

    if not str(file_path).startswith(str(export_dir)) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo de exportación no encontrado")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/db/memberships/expiring", dependencies=[Depends(verify_api_key_guard)])
async def get_expiring_memberships(session: AsyncSession = Depends(get_session)):
    return await MembershipsService.get_expiring_memberships(session)

@router.post("/db/memberships/{membership_id}/mark_notified", dependencies=[Depends(verify_api_key_guard)])
async def mark_membership_notified(membership_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)], notification_type: str, session: AsyncSession = Depends(get_session)):
    if notification_type not in ["3d", "24h"]:
        raise HTTPException(status_code=400, detail="Invalid notification_type")
    success = await MembershipsService.mark_membership_notified(membership_id, notification_type, session)
    if not success:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"ok": True}
