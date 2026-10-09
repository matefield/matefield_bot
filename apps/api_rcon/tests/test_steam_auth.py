from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import BotConfig, Player
from src.security.tokens import (
    generate_signed_payload_token,
    verify_signed_payload_token,
)
from wardogs_schemas.steam_token import create_steam_link_token, verify_steam_link_token


@pytest.mark.asyncio
async def test_steam_token_creation_and_verification():
    secret = "test-secret-key-12345"
    token = create_steam_link_token("123456789", secret, guild_id="987654321", expires_in=60)
    
    # 1. Valid token
    payload = verify_steam_link_token(token, secret)
    assert payload is not None
    assert payload["discord_id"] == "123456789"
    assert payload["guild_id"] == "987654321"
    
    # 2. Wrong secret
    assert verify_steam_link_token(token, "wrong-secret") is None
    
    # 3. Tampered token
    tampered = token[:-4] + "abcd"
    assert verify_steam_link_token(tampered, secret) is None
    
    # 4. Expired token
    expired_token = create_steam_link_token("123456789", secret, expires_in=-10)
    assert verify_steam_link_token(expired_token, secret) is None


def test_signed_browser_payload_is_tamper_proof_and_expires():
    with patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY", "secret_key"):
        token = generate_signed_payload_token({"result": "success"})
        assert verify_signed_payload_token(token)["result"] == "success"
        assert verify_signed_payload_token(f"{token}tampered") is None

        expired_token = generate_signed_payload_token({"result": "success"}, expires_in_seconds=-1)
        assert verify_signed_payload_token(expired_token) is None

@pytest.mark.asyncio
async def test_steam_login_redirect(client: AsyncClient):
    secret = "secret_key"
    with patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY", secret), \
         patch("src.config.ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.PUBLIC_API_URL", "http://testserver"):
        
        # Token inválido
        resp_invalid = await client.get("/api/v1/auth/steam/login?token=invalid.token")
        assert resp_invalid.status_code == 400
        assert "Este enlace venció" in resp_invalid.text
        
        # Token válido
        token = create_steam_link_token("123456789", secret, expires_in=600)
        resp = await client.get(f"/api/v1/auth/steam/login?token={token}", follow_redirects=False)
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "steamcommunity.com/openid/login" in location
        assert "checkid_setup" in location
        assert ("token=" in location or "token%3D" in location)

@pytest.mark.asyncio
async def test_steam_callback_success(client: AsyncClient, session: AsyncSession):
    secret = "secret_key"
    discord_id = "555666777"
    steam_id = "76561198000000888"
    token = create_steam_link_token(discord_id, secret, expires_in=600)
    
    mock_post_resp = MagicMock()
    mock_post_resp.text = "ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"
    
    mock_steam_summary = {
        "personaname": "GamerPro",
        "avatarfull": "https://steamcdn.test/avatar.jpg"
    }

    with patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY", secret), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_post_resp)), \
         patch("src.modules.v1.routers.auth.get_player_summary", new=AsyncMock(return_value=mock_steam_summary)):
        
        params = {
            "token": token,
            "openid.mode": "id_res",
            "openid.claimed_id": f"https://steamcommunity.com/openid/id/{steam_id}",
            "openid.identity": f"https://steamcommunity.com/openid/id/{steam_id}",
            "openid.sig": "validsig123"
        }
        await prepare_callback(client, token, params)
        callback_response = await client.get("/api/v1/auth/steam/callback", params=params)
        assert callback_response.status_code == 303
        assert callback_response.headers["location"] == "/vincular/discord-steam/resultado"
        assert "token" not in callback_response.headers["location"]
        assert "openid" not in callback_response.headers["location"]
        assert callback_response.headers["referrer-policy"] == "no-referrer"
        assert "HttpOnly" in callback_response.headers["set-cookie"]
        assert "SameSite=lax" in callback_response.headers["set-cookie"]

        result_response = await client.get(callback_response.headers["location"])
        assert result_response.status_code == 200
        assert "¡Listo!" in result_response.text
        assert "GamerPro" in result_response.text
        assert "/static/images/BANNER_ICONO_SERVIDOR.png" in result_response.text
        assert "/static/images/steam_icon_black.png" in result_response.text
        assert "https://steamcdn.test/avatar.jpg" in result_response.text
        
        # Verificar en DB
        player = await session.get(Player, steam_id)
        assert player is not None
        assert player.discord_id == discord_id
        assert player.in_game_name == "GamerPro"
        assert player.avatar_url == "https://steamcdn.test/avatar.jpg"

@pytest.mark.asyncio
async def test_steam_callback_with_discord_metadata_and_static_files(client: AsyncClient, session: AsyncSession):
    secret = "secret_key"
    discord_id = "999888777"
    steam_id = "76561198000000999"
    token = create_steam_link_token(
        discord_id=discord_id,
        secret_key=secret,
        guild_id="111222333",
        discord_username="MateoFPS",
        discord_tag="#8314",
        discord_avatar="https://discordcdn.test/mateo.png",
        expires_in=600
    )
    
    mock_post_resp = MagicMock()
    mock_post_resp.text = "ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"
    
    mock_steam_summary = {
        "personaname": "MateoFPS_Steam",
        "avatarfull": "https://steamcdn.test/mateo_steam.jpg",
        "profileurl": f"https://steamcommunity.com/profiles/{steam_id}"
    }

    with patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY", secret), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_post_resp)), \
         patch("src.modules.v1.routers.auth.get_player_summary", new=AsyncMock(return_value=mock_steam_summary)):
        
        params = {
            "token": token,
            "openid.mode": "id_res",
            "openid.claimed_id": f"https://steamcommunity.com/openid/id/{steam_id}",
            "openid.identity": f"https://steamcommunity.com/openid/id/{steam_id}",
            "openid.sig": "validsig123"
        }
        await prepare_callback(client, token, params)
        callback_response = await client.get("/api/v1/auth/steam/callback", params=params)
        assert callback_response.status_code == 303

        result_response = await client.get(callback_response.headers["location"])
        assert result_response.status_code == 200
        assert "¡Listo!" in result_response.text
        assert "MateoFPS_Steam" in result_response.text
        assert "MateoFPS" in result_response.text
        assert "https://discordcdn.test/mateo.png" in result_response.text
        assert "https://steamcdn.test/mateo_steam.jpg" in result_response.text
        
        # Verificar que los archivos estáticos de marca existen y responden HTTP 200
        for img in ["BANNER_ICONO_SERVIDOR.png", "BANNER_FONDO_INVITACION.png", "steam_icon_black.png"]:
            img_resp = await client.get(f"/static/images/{img}")
            assert img_resp.status_code == 200
            assert len(img_resp.content) > 0


@pytest.mark.asyncio
async def test_steam_callback_immediate_role_grant(client: AsyncClient, session: AsyncSession, monkeypatch):
    secret = "secret_key"
    discord_id = "1122334455"
    steam_id = "76561198000000777"
    
    # Configurar LINK_ROLE_ID y GUILD_ID en base de datos
    session.add(BotConfig(config_key="LINK_ROLE_ID", config_value="998877"))
    session.add(BotConfig(config_key="GUILD_ID", config_value="554433"))
    await session.commit()

    monkeypatch.setenv("DISCORD_TOKEN", "mock_discord_token")

    # Token sin guild_id explícito para comprobar fallback a BotConfig
    token = create_steam_link_token(discord_id=discord_id, secret_key=secret, expires_in=600)

    mock_post_resp = MagicMock()
    mock_post_resp.text = "ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"

    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 204
    mock_put = AsyncMock(return_value=mock_put_resp)

    mock_steam_summary = {
        "personaname": "VerifiedUser",
        "avatarfull": "https://steamcdn.test/verified.jpg"
    }

    with patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY", secret), \
         patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.DISCORD_TOKEN", "mock_discord_token"), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_post_resp)), \
         patch("httpx.AsyncClient.put", new=mock_put), \
         patch("src.modules.v1.routers.auth.get_player_summary", new=AsyncMock(return_value=mock_steam_summary)):

        params = {
            "token": token,
            "openid.mode": "id_res",
            "openid.claimed_id": f"https://steamcommunity.com/openid/id/{steam_id}",
            "openid.identity": f"https://steamcommunity.com/openid/id/{steam_id}",
            "openid.sig": "validsig123"
        }
        await prepare_callback(client, token, params)
        resp = await client.get("/api/v1/auth/steam/callback", params=params)
        assert resp.status_code == 303

        # Verificar que se llamó a la API de Discord para otorgar el rol de link inmediatamente
        expected_url = f"https://discord.com/api/v10/guilds/554433/members/{discord_id}/roles/998877"
        mock_put.assert_called_once()
        assert mock_put.call_args[0][0] == expected_url
        assert "Authorization" in mock_put.call_args[1]["headers"]
        assert mock_put.call_args[1]["headers"]["Authorization"] == "Bot mock_discord_token"


@pytest.mark.asyncio
async def test_steam_test_views_are_available_outside_production(client: AsyncClient):
    with patch("src.modules.v1.routers.auth.is_prod", return_value=False):
        success_response = await client.get("/api/v1/auth/steam/test/success")
        error_response = await client.get("/api/v1/auth/steam/test/error")

    assert success_response.status_code == 200
    assert "¡Listo!" in success_response.text
    assert "Viejo Sordo" in success_response.text
    assert "El Nono" in success_response.text
    assert "/static/images/test_discord_avatar.svg" in success_response.text
    assert "/static/images/test_steam_avatar.svg" in success_response.text
    assert error_response.status_code == 200
    assert "No pudimos completar la vinculación" in error_response.text


@pytest.mark.asyncio
async def test_steam_callback_error_redirects_to_clean_url(client: AsyncClient):
    with patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY", "secret_key"):
        callback_response = await client.get(
            "/api/v1/auth/steam/callback",
            params={"token": "invalid.token", "openid.mode": "cancel"},
        )

        assert callback_response.status_code == 303
        assert callback_response.headers["location"] == "/vincular/discord-steam/resultado"
        assert "token" not in callback_response.headers["location"]
        assert "openid" not in callback_response.headers["location"]

        result_response = await client.get(callback_response.headers["location"])
        assert result_response.status_code == 400
        assert "Este enlace venció" in result_response.text
        assert "Volvé a Discord" in result_response.text


@pytest.mark.asyncio
async def test_steam_result_rejects_missing_cookie(client: AsyncClient):
    response = await client.get("/vincular/discord-steam/resultado")

    assert response.status_code == 400
    assert "Este enlace venció" in response.text


@pytest.mark.asyncio
async def test_steam_test_views_are_hidden_in_production(client: AsyncClient):
    with patch("src.modules.v1.routers.auth.is_prod", return_value=True):
        success_response = await client.get("/api/v1/auth/steam/test/success")
        error_response = await client.get("/api/v1/auth/steam/test/error")

    assert success_response.status_code == 404
    assert error_response.status_code == 404


async def prepare_callback(client, token, params):
    login = await client.get("/api/v1/auth/steam/login", params={"token": token})
    return_to = parse_qs(urlparse(login.headers["location"]).query)["openid.return_to"][0]
    params.update({"openid.ns": "http://specs.openid.net/auth/2.0",
                   "openid.op_endpoint": "https://steamcommunity.com/openid/login",
                   "openid.return_to": return_to,
                   "openid.response_nonce": "nonce-verified-by-steam",
                   "openid.assoc_handle": "handle",
                   "openid.signed": "op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle"})
