from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.modules.v1.services.auth_page_service import AuthPageService


def test_auth_page_service_render_success():
    html = AuthPageService.render_success_page(
        discord_name="Comandante",
        discord_avatar="https://discordcdn.test/avatar.png",
        steam_name="Soldado_Mate",
        steam_avatar="https://steamcdn.test/soldado.jpg",
    )
    assert "Comandante" in html
    assert "Soldado_Mate" in html
    assert '<h1 id="success-title">¡Listo!</h1>' in html
    assert '<p class="confirmation">Tu cuenta quedó vinculada.</p>' in html
    assert "Ya podés cerrar esta pestaña y volver a Discord." in html
    assert "MATEFIELD" in html
    assert "COMUNIDAD" in html
    assert "LATINOAMERICANA" in html
    assert "https://discordcdn.test/avatar.png" in html
    assert "https://steamcdn.test/soldado.jpg" in html
    assert "/static/images/discord_square.svg" in html
    assert "/static/images/steam_square.svg" in html
    assert "BANNER_ICONO_SERVIDOR.png" in html
    assert 'class="button" href=' not in html
    assert "cambiar-cuenta" not in html


def test_auth_page_service_render_error():
    html = AuthPageService.render_error_page(
        title="Firma No Válida",
        message="Steam rechazó la firma OpenID.",
    )
    assert "Firma No Válida" in html
    assert "Steam rechazó la firma OpenID." in html
    assert "BANNER_ICONO_SERVIDOR.png" in html
    assert "MATEFIELD" in html
    assert "COMUNIDAD" in html
    assert "LATINOAMERICANA" in html
    assert "{{ERROR_DETAIL}}" not in html


@pytest.mark.asyncio
async def test_auth_page_service_fetch_discord_profile():
    # 1. No token provided
    res_none = await AuthPageService.fetch_discord_profile("12345", None)
    assert res_none["username"] is None

    # 2. Valid response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "username": "mateo",
        "global_name": "Mateo Global",
        "discriminator": "0",
        "avatar": "abcdef123456"
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
        res = await AuthPageService.fetch_discord_profile("12345", "mock_bot_token")
        assert res["username"] == "Mateo Global"
        assert res["avatar_url"] is not None and "abcdef123456.png" in res["avatar_url"]


def test_auth_page_service_xss_escaping():
    malicious_name = '<script>alert("xss")</script>'
    malicious_msg = 'Error" onfocus="alert(1)'
    
    success_html = AuthPageService.render_success_page(
        steam_name=malicious_name,
        discord_name='User<foo>'
    )
    assert malicious_name not in success_html
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in success_html
    assert "<foo>" not in success_html
    assert "&lt;foo&gt;" in success_html

    error_html = AuthPageService.render_error_page(
        title="Error",
        message=malicious_msg,
    )
    assert malicious_msg not in error_html
    assert "Error&quot; onfocus=&quot;alert(1)" in error_html


def test_auth_page_service_missing_template_raises():
    from pathlib import Path
    with patch("src.modules.v1.services.auth_page_service.SUCCESS_TEMPLATE_PATH", Path("/nonexistent/success.html")):
        with pytest.raises(FileNotFoundError) as exc_info:
            AuthPageService.render_success_page()
        assert "no encontrada" in str(exc_info.value)
