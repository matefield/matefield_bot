
import pydantic

from wardogs_config.base import BaseAppConfig


class SecuritySettings(BaseAppConfig):
    """
    Security and authentication settings loaded from environment variables.
    """
    API_KEY: str = pydantic.Field(
        default="default_secret_key",
        validation_alias="API_KEY",
        description="Global API Key for accessing endpoints",
    )
    API_KEY_NAME: str = pydantic.Field(
        default="X-API-Key",
        validation_alias="API_KEY_NAME",
        description="Header name for the API Key",
    )

    # --- Discord integration ---
    DISCORD_TOKEN: str | None = pydantic.Field(
        default=None,
        validation_alias="DISCORD_TOKEN",
        description="Discord bot token for immediate post-link role assignment",
    )
    DISCORD_GUILD_ID: str | None = pydantic.Field(
        default=None,
        validation_alias="DISCORD_GUILD_ID",
        description="Target Discord guild/server ID",
    )
    DISCORD_GUILD_IDS: str | None = pydantic.Field(
        default=None,
        validation_alias="DISCORD_GUILD_IDS",
        description="Comma-separated guild IDs enabled for membership role configuration; falls back to DISCORD_GUILD_ID",
    )
    DISCORD_CLIENT_ID: str | None = pydantic.Field(
        default=None,
        validation_alias="DISCORD_CLIENT_ID",
        description="Discord OAuth2 application client ID",
    )
    DISCORD_CLIENT_SECRET: str | None = pydantic.Field(
        default=None,
        validation_alias="DISCORD_CLIENT_SECRET",
        description="Discord OAuth2 application client secret",
    )
    DISCORD_REDIRECT_URI: str | None = pydantic.Field(
        default=None,
        validation_alias="DISCORD_REDIRECT_URI",
        description="Discord OAuth2 redirect URI",
    )
    ADMIN_SESSION_SECRET: str | None = pydantic.Field(
        default=None,
        validation_alias="ADMIN_SESSION_SECRET",
        description="Secret key to sign admin session tokens (falls back to API_KEY)",
    )

    # --- External Services ---
    STEAM_WEB_API_KEY: str | None = pydantic.Field(
        default=None,
        validation_alias="STEAM_WEB_API_KEY",
        description="Valve Steam Web API Key",
    )
