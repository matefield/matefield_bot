import os
from unittest.mock import patch

from wardogs_config import (
    ConnectionSettings,
    DiscordBotSettings,
    EnvironmentSettings,
    SecuritySettings,
    is_prod,
    resolve_env_file,
)


def test_resolve_env_file_custom_env_file(tmp_path):
    custom_env = tmp_path / "custom.env"
    custom_env.write_text("API_KEY=custom_test_key\n")
    
    with patch.dict(os.environ, {"ENV_FILE": str(custom_env)}):
        resolved = resolve_env_file()
        assert resolved == (str(custom_env),)


def test_resolve_env_file_target_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prod_env = tmp_path / ".env.prod"
    prod_env.write_text("APP_ENV=production\n")

    with patch.dict(os.environ, {"ENV": "prod", "ENV_FILE": ""}, clear=False):
        resolved = resolve_env_file()
        assert resolved == (str(prod_env),)


def test_security_settings_defaults():
    assert SecuritySettings.model_fields["API_KEY"].default == "default_secret_key"
    assert SecuritySettings.model_fields["API_KEY_NAME"].default == "X-API-Key"


def test_security_settings_override():
    with patch.dict(os.environ, {"API_KEY": "super_secret_override"}):
        settings = SecuritySettings()
        assert settings.API_KEY == "super_secret_override"


def test_connection_settings_defaults():
    assert "postgresql+asyncpg" in ConnectionSettings.model_fields["DATABASE_URL"].default
    assert ConnectionSettings.model_fields["SERVER_PORT"].default == 8000


def test_connection_settings_override():
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql+asyncpg://user:pass@db:5432/testdb", "SERVER_PORT": "9000"}):
        settings = ConnectionSettings()
        assert settings.DATABASE_URL == "postgresql+asyncpg://user:pass@db:5432/testdb"
        assert settings.SERVER_PORT == 9000


def test_discord_bot_settings_defaults():
    assert DiscordBotSettings.model_fields["API_BASE_URL"].default == "http://127.0.0.1:8000"
    assert DiscordBotSettings.model_fields["STEAM_LINK_EMOJI"].default == "🎮"
    assert DiscordBotSettings.model_fields["APP_ENV"].default == "development"


def test_discord_bot_settings_override():
    with patch.dict(os.environ, {"DISCORD_TOKEN": "bot_token_xyz", "STEAM_LINK_EMOJI": "🔥", "APP_ENV": "production"}):
        settings = DiscordBotSettings()
        assert settings.DISCORD_TOKEN == "bot_token_xyz"
        assert settings.STEAM_LINK_EMOJI == "🔥"
        assert settings.is_dev is False

    with patch.dict(os.environ, {"APP_ENV": "development"}):
        dev_settings = DiscordBotSettings()
        assert dev_settings.is_dev is True


def test_environment_settings_nested():
    with patch.dict(os.environ, {"APP_ENV": "production", "API_KEY": "prod_key"}):
        settings = EnvironmentSettings()
        assert settings.APP_ENV == "production"
        assert settings.SECURITY_SETTINGS.API_KEY == "prod_key"
        assert is_prod(settings) is True


def test_is_prod_helper():
    dev_settings = EnvironmentSettings(APP_ENV="development")
    assert is_prod(dev_settings) is False

    prod_settings = EnvironmentSettings(APP_ENV="production")
    assert is_prod(prod_settings) is True
