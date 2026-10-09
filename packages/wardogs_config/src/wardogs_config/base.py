import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def resolve_env_file() -> tuple[str, ...]:
    """
    Resolves the .env file path dynamically.
    Priority:
    1. ENV_FILE environment variable (if explicitly set and exists)
    2. Specific environment file according to ENV or APP_ENV (prod, dev, local, test)
    3. .env, .env.local, or .env.dev in current or parent directories
    """
    custom = os.environ.get("ENV_FILE")
    if custom and os.path.exists(custom):
        return (custom,)

    env_name = (os.environ.get("ENV") or os.environ.get("APP_ENV") or "").strip().lower()
    mapping = {
        "prod": ".env.prod",
        "production": ".env.prod",
        "local": ".env.local",
        "dev": ".env.dev",
        "development": ".env.dev",
        "test": ".env.test",
    }
    target = mapping.get(env_name)

    search_dirs = [Path.cwd(), Path.cwd().parent, Path.cwd().parent.parent]

    if target:
        for d in search_dirs:
            p = d / target
            if p.is_file():
                return (str(p),)

    for name in [".env", ".env.local", ".env.dev"]:
        for d in search_dirs:
            p = d / name
            if p.is_file():
                return (str(p),)

    return (".env",)


class BaseAppConfig(BaseSettings):
    """Base settings configuration enabling dotenv loading and ignoring unknown extra fields."""
    model_config = SettingsConfigDict(
        env_file=resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )
