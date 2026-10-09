"""
Configuration module for api_rcon, powered by the centralized wardogs_config package.
"""
from wardogs_config import (
    BOT_SETTINGS,
    ENVIRONMENT_SETTINGS,
    ConnectionSettings,
    DiscordBotSettings,
    EnvironmentSettings,
    SecuritySettings,
    is_prod,
)

__all__ = [
    "BOT_SETTINGS",
    "ENVIRONMENT_SETTINGS",
    "ConnectionSettings",
    "DiscordBotSettings",
    "EnvironmentSettings",
    "SecuritySettings",
    "is_prod",
]
