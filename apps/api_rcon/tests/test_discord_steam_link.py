import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["", "/callback", "/cambiar-cuenta"])
async def test_old_oauth_entries_do_not_authenticate_browser(client, path):
    client.cookies.set("discord_web_session", "old-session")
    response = await client.get("/vincular/discord-steam" + path, params={"discord_id": "123", "code": "ignored"})
    assert response.status_code == 410
    assert "location" not in response.headers
    assert "Volvé a Discord" in response.text
    assert 'href=' not in response.text.split('<body>')[1]
