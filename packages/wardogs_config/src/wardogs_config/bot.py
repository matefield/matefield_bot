import pydantic

from wardogs_config.base import BaseAppConfig


class DiscordBotSettings(BaseAppConfig):
    """
    Configuration settings specifically for the Discord Bot.
    """
    DISCORD_TOKEN: str = pydantic.Field(
        default="tu_token_aqui",
        validation_alias="DISCORD_TOKEN",
        description="Discord bot token",
    )

    API_BASE_URL: str = pydantic.Field(
        default="http://127.0.0.1:8000",
        validation_alias="API_BASE_URL",
        description="Internal base URL of the RCON API server",
    )

    API_KEY: str = pydantic.Field(
        default="default_secret_key",
        validation_alias="API_KEY",
        description="Shared secret API key for bot-to-API communication",
    )

    PUBLIC_API_URL: str = pydantic.Field(
        default="http://localhost:8000",
        validation_alias="PUBLIC_API_URL",
        description="Publicly reachable URL of the API for browser links",
    )

    STEAM_LINK_EMOJI: str = pydantic.Field(
        default="🎮",
        validation_alias="STEAM_LINK_EMOJI",
        description="Emoji used in Discord interactive buttons for Steam account linking",
    )

    APP_ENV: str = pydantic.Field(
        default="development",
        validation_alias="APP_ENV",
        description="Application runtime environment (e.g. development, production, local)",
    )

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV.strip().lower() in ("development", "dev", "local")
