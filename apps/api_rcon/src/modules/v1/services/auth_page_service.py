import html
import logging
from pathlib import Path

import httpx

logger = logging.getLogger("wardogs.auth_pages")

PAGES_DIR = Path(__file__).resolve().parents[4] / "pages" / "steam"
SUCCESS_TEMPLATE_PATH = PAGES_DIR / "success_callback.html"
ERROR_TEMPLATE_PATH = PAGES_DIR / "error_callback.html"


class AuthPageService:
    """Resuelve perfiles y renderiza las pantallas de callback de Steam."""

    @classmethod
    def _load_template(cls, template_path: Path) -> str:
        if not template_path.is_file():
            logger.error("Plantilla HTML no encontrada en el sistema: %s", template_path)
            raise FileNotFoundError(f"Plantilla HTML '{template_path.name}' no encontrada en el servidor.")
        return template_path.read_text(encoding="utf-8")

    @classmethod
    async def fetch_discord_profile(
        cls, discord_id: str, discord_token: str | None
    ) -> dict[str, str | None]:
        result = {"username": None, "avatar_url": None}
        if not discord_token or not discord_id:
            return result

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(
                    f"https://discord.com/api/v10/users/{discord_id}",
                    headers={"Authorization": f"Bot {discord_token}"},
                )
            if response.status_code == 200:
                profile = response.json()
                result["username"] = profile.get("global_name") or profile.get("username")
                avatar_hash = profile.get("avatar")
                if avatar_hash:
                    extension = "gif" if avatar_hash.startswith("a_") else "png"
                    result["avatar_url"] = (
                        f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{extension}"
                    )
        except Exception as error:
            logger.debug("No se pudo resolver el perfil de Discord para %s: %s", discord_id, error)

        return result

    @classmethod
    def render_success_page(
        cls,
        discord_name: str | None = "",
        discord_avatar: str | None = "",
        steam_name: str | None = "",
        steam_avatar: str | None = "",
        already_linked: bool = False,
    ) -> str:
        return cls._render_template(
            SUCCESS_TEMPLATE_PATH,
            {
                "{{SUCCESS_TITLE}}": "Tu cuenta ya está vinculada" if already_linked else "¡Listo!",
                "{{SUCCESS_CONFIRMATION}}": "" if already_linked else "Tu cuenta quedó vinculada.",
                "{{SUCCESS_SUBTITLE}}": (
                    "No tenés que hacer nada más."
                    if already_linked else "Ya podés cerrar esta pestaña y volver a Discord."
                ),
                "{{DISCORD_NAME}}": discord_name or "Usuario",
                "{{DISCORD_AVATAR}}": discord_avatar or "https://cdn.discordapp.com/embed/avatars/0.png",
                "{{STEAM_NAME}}": steam_name or "Jugador",
                "{{STEAM_AVATAR}}": steam_avatar or "/static/images/steam_icon_black.png",
            },
        )

    @classmethod
    def render_error_page(cls, title: str, message: str) -> str:
        return cls._render_template(
            ERROR_TEMPLATE_PATH,
            {
                "{{ERROR_TITLE}}": title or "Error de vinculación",
                "{{ERROR_MESSAGE}}": message or "Ocurrió un error inesperado al procesar la vinculación.",
            },
        )

    @classmethod
    def _render_template(cls, template_path: Path, replacements: dict[str, str]) -> str:
        content = cls._load_template(template_path)
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, html.escape(value, quote=True))
        return content
