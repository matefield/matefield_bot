import logging
import urllib.parse
from typing import Any

import httpx
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_config import ENVIRONMENT_SETTINGS

from src.connections.databases.db import BotConfig, Player, Role

logger = logging.getLogger("wardogs.discord_oauth")

DISCORD_API_BASE = "https://discord.com/api/v10"
ADMINISTRATOR_PERMISSION = 0x8  # Permission bit 3

# Resolved once after load_dotenv() — avoids os.environ scatter
_security = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS

class DiscordOAuthService:
    @staticmethod
    def get_client_id() -> str | None:
        return _security.DISCORD_CLIENT_ID

    @staticmethod
    def get_client_secret() -> str | None:
        return _security.DISCORD_CLIENT_SECRET

    @classmethod
    def get_authorization_url(cls, redirect_uri: str, state: str = "") -> str:
        client_id = cls.get_client_id()
        if not client_id:
            raise ValueError("DISCORD_CLIENT_ID no está configurado.")

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "identify guilds guilds.members.read",
            "prompt": "consent",
        }
        if state:
            params["state"] = state

        return f"https://discord.com/oauth2/authorize?{urllib.parse.urlencode(params)}"

    @classmethod
    async def exchange_code_for_token(cls, code: str, redirect_uri: str) -> dict[str, Any]:
        client_id = cls.get_client_id()
        client_secret = cls.get_client_secret()

        if not client_id or not client_secret:
            raise ValueError("DISCORD_CLIENT_ID o DISCORD_CLIENT_SECRET no configurados.")

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{DISCORD_API_BASE}/oauth2/token", data=data, headers=headers)
            if resp.status_code != 200:
                logger.error("Error al canjear código Discord OAuth: %s", resp.text)
                raise ValueError(f"Fallo al autenticar con Discord: {resp.text}")
            return resp.json()

    @classmethod
    async def fetch_user_profile(cls, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)
            if resp.status_code != 200:
                raise ValueError(f"No se pudo obtener el perfil de usuario de Discord: {resp.text}")
            data = resp.json()

            discord_id = data.get("id")
            avatar_hash = data.get("avatar")
            if avatar_hash:
                ext = "gif" if avatar_hash.startswith("a_") else "png"
                avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{ext}"
            else:
                avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"

            return {
                "id": str(discord_id),
                "username": data.get("global_name") or data.get("username"),
                "avatar_url": avatar_url,
            }

    @classmethod
    async def resolve_guild_id(cls, session: AsyncSession) -> str | None:
        # 1. Check explicit settings
        configured = _security.DISCORD_GUILD_ID
        if configured:
            return str(configured).strip()

        # 2. Check bot_config table
        cfg = await session.get(BotConfig, "GUILD_ID")
        if cfg and cfg.config_value:
            return str(cfg.config_value).strip()

        # 3. Autodetect from bot's guild list
        bot_token = _security.DISCORD_TOKEN
        if bot_token:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{DISCORD_API_BASE}/users/@me/guilds",
                        headers={"Authorization": f"Bot {bot_token}"},
                    )
                    if resp.status_code == 200:
                        bot_guilds = resp.json()
                        if bot_guilds:
                            discovered_id = str(bot_guilds[0]["id"])
                            logger.info("GUILD_ID resuelto dinámicamente desde el bot: %s", discovered_id)
                            return discovered_id
            except Exception as e:
                logger.debug("No se pudo autodetectar guild del bot: %s", e)

        return None

    @classmethod
    async def verify_admin_status(
        cls,
        discord_id: str,
        access_token: str,
        session: AsyncSession,
    ) -> tuple[bool, str, str | None]:
        """
        Determina si un usuario tiene privilegios de administrador.
        Retorna (is_admin, motivo, guild_id).
        """
        guild_id = await cls.resolve_guild_id(session)
        if not guild_id:
            return False, "No se ha configurado DISCORD_GUILD_ID ni se pudo autodetectar el servidor del bot.", None

        headers = {"Authorization": f"Bearer {access_token}"}
        bot_token = _security.DISCORD_TOKEN
        member_roles: list[str] = []

        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1. Verificar si el usuario tiene permiso ADMINISTRATOR o es dueño en el servidor objetivo
            try:
                resp = await client.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers)
                if resp.status_code == 200:
                    guilds = resp.json()
                    target_guild = next((g for g in guilds if str(g.get("id")) == guild_id), None)
                    if target_guild:
                        is_owner = target_guild.get("owner", False)
                        raw_perms = target_guild.get("permissions")
                        try:
                            perms = int(raw_perms) if raw_perms is not None else 0
                        except (ValueError, TypeError):
                            perms = 0
                        has_admin_perm = (perms & ADMINISTRATOR_PERMISSION) == ADMINISTRATOR_PERMISSION

                        if is_owner or has_admin_perm:
                            return True, "Permiso nativo de Administrador en Discord", guild_id
            except Exception as e:
                logger.warning("Error consultando gremios de usuario en Discord: %s", e)

            # 2. Si no es admin por permiso nativo, verificar roles asignados en el servidor objetivo
            try:
                resp = await client.get(
                    f"{DISCORD_API_BASE}/users/@me/guilds/{guild_id}/member",
                    headers=headers,
                )
                if resp.status_code == 200:
                    member_data = resp.json()
                    member_roles = [str(r) for r in member_data.get("roles", [])]
            except Exception:
                pass

            # Fallback vía Bot Token si guilds.members.read no trajo los roles
            if not member_roles and bot_token:
                try:
                    resp = await client.get(
                        f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{discord_id}",
                        headers={"Authorization": f"Bot {bot_token}"},
                    )
                    if resp.status_code == 200:
                        member_data = resp.json()
                        member_roles = [str(r) for r in member_data.get("roles", [])]
                except Exception:
                    pass

        if member_roles:
            # Consultar roles SYSTEM en BD de forma optimizada (insensible a mayúsculas/minúsculas)
            roles_result = await session.exec(
                select(Role).where(
                    Role.discord_role_id.is_not(None),
                    (func.upper(Role.role_type) == "SYSTEM") | (func.upper(Role.role_type).like("SYSTEM%")),
                )
            )
            db_roles = roles_result.all()
            admin_role_ids = {
                str(r.discord_role_id).strip()
                for r in db_roles
                if r.discord_role_id and str(r.discord_role_id).strip().isdigit()
            }

            # Incluir roles administrativos configurados en bot_config (ADMIN_ROLE_ID, OWNER_ROLE_ID)
            for cfg_key in ("ADMIN_ROLE_ID", "OWNER_ROLE_ID"):
                cfg = await session.get(BotConfig, cfg_key)
                if cfg and cfg.config_value and cfg.config_value.strip().isdigit():
                    admin_role_ids.add(cfg.config_value.strip())

            matched = set(member_roles).intersection(admin_role_ids)
            if matched:
                return True, "Rol administrativo (SYSTEM / Staff) registrado en BD", guild_id

        return False, "Usuario no posee permisos de Administrador ni rol SYSTEM", guild_id


    @classmethod
    async def get_linked_steam_id(cls, discord_id: str, session: AsyncSession) -> tuple[str | None, str | None, str | None]:
        """Busca si el usuario de Discord ya tiene cuenta vinculada en la base de datos."""
        query = select(Player).where(Player.discord_id == str(discord_id))
        res = await session.exec(query)
        player = res.first()
        if player:
            return player.steam_id, player.in_game_name, player.avatar_url
        return None, None, None
