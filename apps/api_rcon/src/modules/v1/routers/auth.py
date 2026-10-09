import hashlib
import logging
import re
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_config import ENVIRONMENT_SETTINGS, is_prod
from wardogs_schemas.steam_token import verify_steam_link_token

from src.connections.apis.steam import get_player_summary
from src.connections.databases.db import (
    BotConfig,
    Player,
    SteamLinkRedemption,
    get_session,
)
from src.modules.v1.schemas.dtos import LinkAccountRequest
from src.modules.v1.services import AuthPageService, PlayersService
from src.security.tokens import (
    generate_signed_payload_token,
    verify_signed_payload_token,
)

router = APIRouter(prefix="/auth/steam", tags=["Auth"])
logger = logging.getLogger("wardogs.auth")

# Resolved once after load_dotenv() — consistent with the rest of the system.
_security = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS
_connections = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS

STEAM_RESULT_COOKIE = "steam_auth_result"
STEAM_RESULT_PATH = "/vincular/discord-steam/resultado"

render_success_page = AuthPageService.render_success_page
render_error_page = AuthPageService.render_error_page


def _uses_https(request: Request) -> bool:
    public_api_url = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.PUBLIC_API_URL.strip()
    return public_api_url.startswith("https://") or request.url.scheme == "https"


def _redirect_to_result(request: Request, payload: dict) -> RedirectResponse:
    response = RedirectResponse(url=STEAM_RESULT_PATH, status_code=303)
    response.set_cookie(
        key=STEAM_RESULT_COOKIE,
        value=generate_signed_payload_token(payload),
        max_age=300,
        httponly=True,
        secure=_uses_https(request),
        samesite="lax",
        path=STEAM_RESULT_PATH,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


ERROR_TITLE = "No pudimos completar la vinculación"
ERROR_MESSAGE = "Volvé a Discord e intentá de nuevo. Si vuelve a pasar, contactá al equipo del servidor."
EXPIRED_TITLE = "Este enlace venció"
EXPIRED_MESSAGE = "Volvé a Discord y tocá “Vincular mi cuenta de Steam” para empezar de nuevo."
CONFLICT_TITLE = "Esta cuenta de Steam ya está vinculada a otra cuenta de Discord"
CONFLICT_MESSAGE = "Si necesitás ayuda, contactá al equipo del servidor."


def _redirect_to_error(request: Request, message: str = ERROR_MESSAGE, status_code: int = 400,
                       title: str = ERROR_TITLE) -> RedirectResponse:
    return _redirect_to_result(request, {"result": "error", "title": title,
                                        "message": message, "status_code": status_code})


def _token_hash(token: str) -> str:
    # Hash the signed payload, so alternate base64 padding of the signature cannot bypass redemption.
    return hashlib.sha256(token.split(".", 1)[0].encode()).hexdigest()


def _attempt_cookie(token: str) -> str:
    return "steam_attempt_" + _token_hash(token)[:24]


def _public_base_url(request: Request) -> str:
    return (ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.PUBLIC_API_URL.strip() or str(request.base_url)).rstrip("/")


def _return_to(request: Request, token: str) -> str:
    return f"{_public_base_url(request)}/api/v1/auth/steam/callback?{urllib.parse.urlencode({'token': token})}"


def _has_attempt(request: Request, token: str) -> bool:
    saved = verify_signed_payload_token(request.cookies.get(_attempt_cookie(token), ""))
    return bool(saved and saved.get("purpose") == "steam_attempt" and saved.get("token_hash") == _token_hash(token))


def _deny_test_routes_in_prod() -> None:
    if is_prod():
        raise HTTPException(status_code=404, detail="Test routes are unavailable in production")


async def _already_linked_response(request: Request, payload: dict, session: AsyncSession):
    player = (await session.exec(
        select(Player).where(Player.discord_id == str(payload["discord_id"]))
    )).first()
    if player is None:
        return None
    return _redirect_to_result(request, {
        "result": "already_linked", "status_code": 200,
        "discord_name": payload.get("discord_username") or "Tu cuenta de Discord",
        "discord_avatar": payload.get("discord_avatar"),
        "steam_name": player.in_game_name or "Tu cuenta de Steam",
        "steam_avatar": player.avatar_url,
    })


@router.get("/login")
async def steam_login(request: Request, token: str = "", session: AsyncSession = Depends(get_session)):
    payload = verify_steam_link_token(token, _security.API_KEY)
    if not payload:
        return HTMLResponse(render_error_page(title=EXPIRED_TITLE, message=EXPIRED_MESSAGE),
                            status_code=400, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    already = await _already_linked_response(request, payload, session)
    if already is not None:
        return already
    if await session.get(SteamLinkRedemption, _token_hash(token)):
        return _redirect_to_error(request, EXPIRED_MESSAGE, title=EXPIRED_TITLE)

    return_to = _return_to(request, token)
    realm = f"{_public_base_url(request)}/"

    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    
    steam_auth_url = f"https://steamcommunity.com/openid/login?{urllib.parse.urlencode(params)}"
    response = RedirectResponse(steam_auth_url, status_code=303)
    response.set_cookie(_attempt_cookie(token), generate_signed_payload_token(
        {"purpose": "steam_attempt", "token_hash": _token_hash(token)}, expires_in_seconds=600
    ), max_age=600, httponly=True, secure=_uses_https(request), samesite="lax", path="/api/v1/auth/steam/callback")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/callback")
async def steam_callback(request: Request, token: str = "", session: AsyncSession = Depends(get_session)):
    payload = verify_steam_link_token(token, _security.API_KEY)

    if not payload:
        return _redirect_to_error(request, EXPIRED_MESSAGE, title=EXPIRED_TITLE)
    already = await _already_linked_response(request, payload, session)
    if already is not None:
        return already
    if await session.get(SteamLinkRedemption, _token_hash(token)):
        return _redirect_to_error(request, EXPIRED_MESSAGE, title=EXPIRED_TITLE)
    if not _has_attempt(request, token):
        return _redirect_to_error(request)

    discord_id = payload["discord_id"]
    guild_id = payload.get("guild_id")
    query_params = dict(request.query_params)
    if query_params.get("openid.mode") == "cancel":
        return _redirect_to_error(request, "Volvé a Discord cuando quieras intentarlo de nuevo.",
                                  title="Cancelaste la vinculación")
    claimed = query_params.get("openid.claimed_id", "")
    signed = set(query_params.get("openid.signed", "").split(","))
    required = {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce", "assoc_handle"}
    if (query_params.get("openid.mode") != "id_res"
            or query_params.get("openid.ns") != "http://specs.openid.net/auth/2.0"
            or query_params.get("openid.op_endpoint") != "https://steamcommunity.com/openid/login"
            or query_params.get("openid.return_to") != _return_to(request, token)
            or query_params.get("openid.identity") != claimed
            or not required.issubset(signed)):
        return _redirect_to_error(request)
    check_params = {k: v for k, v in query_params.items() if k.startswith("openid.")}
    check_params["openid.mode"] = "check_authentication"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://steamcommunity.com/openid/login", data=check_params)
            resp.raise_for_status()
            if "is_valid:true" not in resp.text.splitlines():
                return _redirect_to_error(request)
    except Exception:
        logger.warning("Steam verification unavailable")
        return _redirect_to_error(request, status_code=502)

    # Extraer Steam ID 64
    match = re.fullmatch(r"https://steamcommunity.com/openid/id/(\d{17})", claimed)
    if not match:
        return _redirect_to_error(
            request,
            ERROR_MESSAGE,
        )

    steam_id = match.group(1)
    discord_id_str = str(discord_id)

    # Vincular cuenta en la base de datos
    try:
        link_req = LinkAccountRequest(discord_id=discord_id_str, steam_id=steam_id)
        linked = await PlayersService.link_account(link_req, session, redemption=SteamLinkRedemption(
            token_hash=_token_hash(token), expires_at=payload["exp"]))
        if linked.get("already_linked"):
            return await _already_linked_response(request, payload, session) or _redirect_to_error(request)
    except HTTPException:
        already = await _already_linked_response(request, payload, session)
        if already is not None:
            return already
        return _redirect_to_error(request, CONFLICT_MESSAGE, status_code=409, title=CONFLICT_TITLE)

    # Obtener nombre y avatar de Steam
    player_name = None
    avatar_url = None
    try:
        steam_profile = await get_player_summary(steam_id)
        if steam_profile:
            player_name = steam_profile.get("personaname")
            avatar_url = steam_profile.get("avatarfull")
            player = await session.get(Player, steam_id)
            if player:
                if player_name:
                    player.in_game_name = player_name
                if avatar_url:
                    player.avatar_url = avatar_url
                session.add(player)
                await session.commit()
    except Exception:
        await session.rollback()

    # Resolver guild_id si no vino en el token (ej: link solicitado por DM)
    if not guild_id:
        cfg_guild = await session.get(BotConfig, "GUILD_ID")
        if cfg_guild and cfg_guild.config_value:
            guild_id = cfg_guild.config_value
        elif _security.DISCORD_GUILD_ID:
            guild_id = str(_security.DISCORD_GUILD_ID)

    # Asignar roles en Discord de forma inmediata si se dispone de token y guild
    discord_token = _security.DISCORD_TOKEN
    if not discord_token:
        logger.warning("DISCORD_TOKEN no configurado en api_rcon. La asignación del rol deberá esperar a la sincronización en segundo plano del bot.")
    if discord_token and guild_id:
        try:
            cfg_link = await session.get(BotConfig, "LINK_ROLE_ID")
            target_role = None
            reason = ""
            if cfg_link and cfg_link.config_value and cfg_link.config_value.isdigit():
                target_role = cfg_link.config_value
                reason = "Rol verificado asignado inmediatamente por vincular cuenta"

            if target_role:
                async with httpx.AsyncClient(timeout=5.0) as discord_client:
                    headers = {
                        "Authorization": f"Bot {discord_token}",
                        "X-Audit-Log-Reason": urllib.parse.quote(reason),
                    }
                    role_url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_id_str}/roles/{target_role}"
                    # Se incluye json={} para garantizar cabeceras Content-Type y Content-Length requeridas por Discord / Cloudflare
                    resp = await discord_client.put(role_url, headers=headers, json={})
                    if resp.status_code in (200, 204):
                        logger.info(f"Rol {target_role} asignado exitosamente a Discord {discord_id_str} en guild {guild_id}")
                    else:
                        logger.warning(
                            f"No se pudo asignar rol {target_role} a Discord {discord_id_str} en guild {guild_id}: "
                            f"HTTP {resp.status_code} - {resp.text}"
                        )
        except Exception as e:
            logger.warning(f"Error al asignar rol de Discord inmediatamente tras vinculación: {e}")

    # Obtener metadatos de Discord desde el payload o Discord REST API
    discord_username = payload.get("discord_username")
    discord_avatar = payload.get("discord_avatar")

    if discord_token and (not discord_username or not discord_avatar):
        dc_profile = await AuthPageService.fetch_discord_profile(discord_id_str, discord_token)
        if not discord_username:
            discord_username = dc_profile["username"]
        if not discord_avatar and dc_profile["avatar_url"]:
            discord_avatar = dc_profile["avatar_url"]

    if not discord_username:
        discord_username = "Tu cuenta de Discord"
    if not discord_avatar:
        discord_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"

    if not player_name or not avatar_url:
        existing_p = await session.get(Player, steam_id)
        if not player_name and existing_p and existing_p.in_game_name:
            player_name = existing_p.in_game_name
        if not avatar_url and existing_p and existing_p.avatar_url:
            avatar_url = existing_p.avatar_url

    if not player_name:
        player_name = "Tu cuenta de Steam"
    if not avatar_url:
        avatar_url = "/static/images/steam_icon_black.png"

    return _redirect_to_result(
        request,
        {
            "result": "success",
            "discord_name": discord_username,
            "discord_avatar": discord_avatar,
            "steam_name": player_name,
            "steam_avatar": avatar_url,
            "status_code": 200,
        },
    )


@router.get("/result", name="steam_auth_result")
async def steam_auth_result(request: Request):
    token = request.cookies.get(STEAM_RESULT_COOKIE, "")
    payload = verify_signed_payload_token(token)
    if not payload:
        html = render_error_page(
            title=EXPIRED_TITLE,
            message=EXPIRED_MESSAGE,
        )
        return HTMLResponse(content=html, status_code=400, headers={"Cache-Control": "no-store"})

    status_code = int(payload.get("status_code", 200))
    if payload.get("result") in {"success", "already_linked"}:
        html = render_success_page(
            discord_name=payload.get("discord_name"),
            discord_avatar=payload.get("discord_avatar"),
            steam_name=payload.get("steam_name"),
            steam_avatar=payload.get("steam_avatar"),
            already_linked=payload.get("result") == "already_linked",
        )
    else:
        html = render_error_page(
            title=payload.get("title", ERROR_TITLE),
            message=payload.get("message", ERROR_MESSAGE),
        )

    return HTMLResponse(content=html, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/test/success")
async def steam_callback_test_success():
    _deny_test_routes_in_prod()

    html = render_success_page(
        discord_name="Viejo Sordo",
        discord_avatar="/static/images/test_discord_avatar.svg",
        steam_name="El Nono",
        steam_avatar="/static/images/test_steam_avatar.svg",
    )
    return HTMLResponse(content=html, status_code=200)


@router.get("/test/error")
async def steam_callback_test_error():
    _deny_test_routes_in_prod()

    html = render_error_page(
        title=ERROR_TITLE,
        message=ERROR_MESSAGE,
    )
    return HTMLResponse(content=html, status_code=200)
