"""
Environment settings re-exported from centralized wardogs_config package.
"""
from wardogs_config.environment import (
    ENVIRONMENT_SETTINGS,
    EnvironmentSettings,
    is_prod,
)

__all__ = ["ENVIRONMENT_SETTINGS", "EnvironmentSettings", "is_prod"]
