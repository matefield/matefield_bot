"""Public result page; identities originate exclusively in Discord interactions."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.modules.v1.routers.auth import (
    EXPIRED_MESSAGE,
    EXPIRED_TITLE,
    steam_auth_result,
)
from src.modules.v1.services.auth_page_service import AuthPageService

router = APIRouter(prefix="/vincular/discord-steam", tags=["Auth"])


@router.get("/resultado")
async def discord_steam_result(request: Request):
    return await steam_auth_result(request)


@router.get("")
@router.get("/callback")
@router.get("/cambiar-cuenta")
async def retired_web_entry():
    response = HTMLResponse(AuthPageService.render_error_page(EXPIRED_TITLE, EXPIRED_MESSAGE),
                            status_code=410, headers={"Cache-Control": "no-store"})
    response.delete_cookie("discord_web_session", path="/")
    return response
