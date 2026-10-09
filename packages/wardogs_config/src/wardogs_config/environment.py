
import pydantic

from wardogs_config.base import BaseAppConfig
from wardogs_config.bot import DiscordBotSettings
from wardogs_config.connections import ConnectionSettings
from wardogs_config.security import SecuritySettings


class EnvironmentSettings(BaseAppConfig):
    """
    Main runtime environment configuration combining security and connections.
    """
    APP_ENV: str = pydantic.Field(
        default="development",
        validation_alias="APP_ENV",
        description="Application runtime environment (e.g. development, production, local, test)",
    )

    SECURITY_SETTINGS: SecuritySettings = pydantic.Field(
        default_factory=SecuritySettings,
        description="Security and authentication settings",
    )

    CONNECTIONS_SETTINGS: ConnectionSettings = pydantic.Field(
        default_factory=ConnectionSettings,
        description="Database, RCON and network connection settings",
    )


ENVIRONMENT_SETTINGS = EnvironmentSettings()
BOT_SETTINGS = DiscordBotSettings()


def is_prod(settings: EnvironmentSettings | None = None) -> bool:
    """Returns True if the current application environment is production."""
    target = settings or ENVIRONMENT_SETTINGS
    return target.APP_ENV.strip().lower() == "production"
