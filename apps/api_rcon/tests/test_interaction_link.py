from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
from src.connections.databases.db import Player
from src.security.tokens import generate_signed_payload_token
from test_steam_auth import prepare_callback
from wardogs_schemas.steam_token import create_steam_link_token, verify_steam_link_token

A, B = "123456789012345678", "223456789012345678"
S, T = "76561198000000888", "76561198000000999"

@pytest.fixture(autouse=True)
def settings():
    with patch("src.config.ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY", "test_key"), \
         patch("src.config.ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.PUBLIC_API_URL", "http://test"):
        yield


def token(discord=A, **kwargs):
    return create_steam_link_token(discord, "test_key", discord_username="Discord A" if discord == A else "Discord B",
                                   discord_avatar="https://example.test/avatar.png", **kwargs)


def params(link, steam=S):
    return {"token": link, "openid.mode": "id_res", "openid.claimed_id": "https://steamcommunity.com/openid/id/" + steam,
            "openid.identity": "https://steamcommunity.com/openid/id/" + steam}


@pytest.mark.asyncio
async def test_discord_identity_from_signed_link_ignores_browser_and_query(client, session):
    client.cookies.set("discord_web_session", generate_signed_payload_token({"discord_id": B, "purpose": "discord_web_session"}))
    link = token()
    login = await client.get("/api/v1/auth/steam/login", params={"token": link, "discord_id": B})
    assert urlparse(login.headers["location"]).hostname == "steamcommunity.com"
    assert "HttpOnly" in login.headers["set-cookie"]
    query = params(link)
    query["discord_id"] = B
    await prepare_callback(client, link, query)
    verified = MagicMock(text="is_valid:true\n")
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=verified)) as post, \
         patch("src.modules.v1.routers.auth.get_player_summary", new=AsyncMock(return_value={"personaname": "Steam A"})) as summary:
        response = await client.get("/api/v1/auth/steam/callback", params=query)
        page = await client.get(response.headers["location"])
        assert "¡Listo!" in page.text
        assert "Discord A" in page.text and "Discord B" not in page.text
        assert 'class="button" href=' not in page.text and "cambiar-cuenta" not in page.text
        again = await client.get("/api/v1/auth/steam/callback", params=query)
        assert "ya está vinculada" in (await client.get(again.headers["location"])).text
        post.assert_awaited_once()
        summary.assert_awaited_once()
    assert (await session.get(Player, S)).discord_id == A
    # Consumed links cannot link again even after a deliberate unlink.
    player = await session.get(Player, S)
    player.discord_id = None
    await session.commit()
    for endpoint in ["login", "callback"]:
        response = await client.get("/api/v1/auth/steam/" + endpoint, params=query)
        assert "Este enlace venció" in (await client.get(response.headers["location"])).text
    assert (await session.get(Player, S)).discord_id is None
    padded = link + "="
    assert verify_steam_link_token(padded, "test_key") is not None
    response = await client.get("/api/v1/auth/steam/login", params={"token": padded})
    assert "Este enlace venció" in (await client.get(response.headers["location"])).text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["expired", "tampered", "unsigned_id"])
async def test_bad_link_never_uses_query_identity(client, mode):
    link = token(expires_in=-1) if mode == "expired" else token() + "bad"
    if mode == "unsigned_id":
        link = ""
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        login = await client.get("/api/v1/auth/steam/login", params={"token": link, "discord_id": A})
        assert login.status_code == 400 and "Este enlace venció" in login.text
        callback = await client.get("/api/v1/auth/steam/callback", params={"token": link})
        assert "Este enlace venció" in (await client.get(callback.headers["location"])).text
        post.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_link_rechecked_before_steam_and_callback(client, session):
    link = token()
    session.add(Player(steam_id=S, discord_id=A, in_game_name="Saved Steam"))
    await session.commit()
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        for endpoint in ["login", "callback"]:
            response = await client.get("/api/v1/auth/steam/" + endpoint, params=params(link, T))
            page = await client.get(response.headers["location"])
            assert "ya está vinculada" in page.text and "Saved Steam" in page.text
        post.assert_not_awaited()
    assert await session.get(Player, T) is None


@pytest.mark.asyncio
async def test_other_discords_steam_never_replaced_or_exposed(client, session):
    session.add(Player(steam_id=S, discord_id=B, in_game_name="Private name"))
    await session.commit()
    link = token()
    query = params(link)
    await prepare_callback(client, link, query)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=MagicMock(text="is_valid:true\n"))):
        response = await client.get("/api/v1/auth/steam/callback", params=query)
    page = await client.get(response.headers["location"])
    assert page.status_code == 409
    assert "Esta cuenta de Steam ya está vinculada a otra cuenta de Discord" in page.text
    assert "Private name" not in page.text and B not in page.text and S not in page.text
    assert (await session.get(Player, S)).discord_id == B


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing_cookie", "swapped_return", "unsigned_return", "wrong_identity", "invalid_signature", "network_error"])
async def test_callback_binding_and_steam_verification(client, session, mode):
    link = token()
    query = params(link)
    await prepare_callback(client, link, query)
    if mode == "missing_cookie": client.cookies.clear()
    if mode == "swapped_return": query["openid.return_to"] = query["openid.return_to"].replace(link, token(B))
    if mode == "unsigned_return": query["openid.signed"] = "claimed_id,identity"
    if mode == "wrong_identity": query["openid.identity"] += "1"
    post = AsyncMock(return_value=MagicMock(text="is_valid:false\n"))
    if mode == "network_error": post.side_effect = RuntimeError("internal-secret-token")
    with patch("httpx.AsyncClient.post", new=post):
        response = await client.get("/api/v1/auth/steam/callback", params=query)
    page = await client.get(response.headers["location"])
    assert "No pudimos completar la vinculación" in page.text
    assert "internal-secret-token" not in page.text
    assert await session.get(Player, S) is None


@pytest.mark.asyncio
async def test_two_discord_accounts_in_same_browser_keep_independent_attempts(client, session):
    a, b = token(A), token(B)
    qa, qb = params(a, S), params(b, T)
    await prepare_callback(client, a, qa)
    await prepare_callback(client, b, qb)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=MagicMock(text="is_valid:true\n"))), \
         patch("src.modules.v1.routers.auth.get_player_summary", new=AsyncMock(return_value=None)):
        for query in [qa, qb]:
            response = await client.get("/api/v1/auth/steam/callback", params=query)
            assert "¡Listo!" in (await client.get(response.headers["location"])).text
    assert (await session.get(Player, S)).discord_id == A
    assert (await session.get(Player, T)).discord_id == B


@pytest.mark.asyncio
async def test_bot_lookup_requires_api_key(client):
    from src.main import app
    from src.security.guard import verify_api_key_guard
    override = app.dependency_overrides.pop(verify_api_key_guard)
    try:
        response = await client.get("/api/v1/db/players/discord/" + A)
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides[verify_api_key_guard] = override


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["login", "callback"])
async def test_incomplete_link_shows_recovery_page_instead_of_validation_json(client, endpoint):
    response = await client.get("/api/v1/auth/steam/" + endpoint, follow_redirects=True)
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Este enlace venció" in response.text


@pytest.mark.asyncio
async def test_steam_cancel_is_terminal_without_external_calls_or_mapping(client, session):
    link = token()
    query = params(link)
    await prepare_callback(client, link, query)
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        response = await client.get("/api/v1/auth/steam/callback", params={"token": link, "openid.mode": "cancel"})
        page = await client.get(response.headers["location"])
        assert "Cancelaste la vinculación" in page.text
        post.assert_not_awaited()
    assert await session.get(Player, S) is None
