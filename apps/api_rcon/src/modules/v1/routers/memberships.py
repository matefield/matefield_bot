from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas import v1 as schemas

from src.connections.databases.db import get_session
from src.modules.v1.schemas.dtos import (
    AddMembershipRequest,
    CompensateRequest,
    EditMembershipRequest,
)
from src.modules.v1.services.export_service import (
    generate_export_download_token,
    generate_memberships_csv,
    get_export_dir,
    verify_export_download_token,
)
from src.modules.v1.services.memberships_service import MembershipsService
from src.security.guard import verify_api_key_guard

router = APIRouter(tags=["Memberships"])

# TTL for the one-time CSV export download token
_EXPORT_TOKEN_TTL_SECONDS = 1800  # 30 minutes

@router.post("/db/players/membership", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def add_membership(req: AddMembershipRequest, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.add_membership(req, session)

@router.put("/db/memberships/{membership_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def edit_membership(membership_id: int, req: EditMembershipRequest, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.edit_membership(membership_id, req, session)

@router.post("/db/memberships/compensate", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def compensate_memberships(req: CompensateRequest, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.compensate_memberships(req.days, session)

@router.delete("/db/memberships/{membership_id}", dependencies=[Depends(verify_api_key_guard)], response_model=schemas.Ok)
async def delete_membership(membership_id: int, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.delete_membership(membership_id, session)

@router.get("/db/memberships", dependencies=[Depends(verify_api_key_guard)])
async def get_paginated_memberships(page: int = 1, limit: int = 10, discord_id: str | None = None, session: AsyncSession = Depends(get_session)):
    return await MembershipsService.get_paginated_memberships(page, limit, session, discord_id=discord_id)

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
