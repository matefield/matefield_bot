from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import hikari
import pytest
from src.plugins import account
from wardogs_schemas import v1 as schemas
from wardogs_schemas.steam_token import verify_steam_link_token

A, B = 123456789012345678, 223456789012345678

@pytest.fixture
def client():
    client = MagicMock()
    client.model.api.api_key = "test_key"
    client.model.public_api_url = "http://test"
    client.model.api.get_player_by_discord = AsyncMock(return_value=None)
    account.plugin._client = client
    return client


def event(user_id=A):
    interaction = MagicMock(spec=hikari.ComponentInteraction)
    interaction.custom_id = "btn_start_steam_link"
    interaction.user = MagicMock(id=user_id, global_name="Name **bold** <@123> @everyone", username="user", discriminator="0")
    interaction.guild_id = 999
    interaction.create_initial_response = AsyncMock()
    interaction.edit_initial_response = AsyncMock()
    return MagicMock(interaction=interaction)


@pytest.mark.asyncio
async def test_persistent_handler_uses_each_clickers_identity_and_private_response(client):
    # Invoke registered gateway callback twice without any per-message registration/cache.
    for user_id in [A, B]:
        ev = event(user_id)
        await account.on_steam_link_button_click.metadata.callback(ev)
        ev.interaction.create_initial_response.assert_awaited_once_with(
            hikari.ResponseType.DEFERRED_MESSAGE_CREATE, flags=hikari.MessageFlag.EPHEMERAL)
        client.model.api.get_player_by_discord.assert_awaited_with(str(user_id))
        reply = ev.interaction.edit_initial_response.call_args.kwargs
        assert reply["embed"].title == "Vinculá tu cuenta de Steam"
        assert reply["embed"].description == (
            "Vas a vincular esta cuenta de Discord con la cuenta de Steam con la que inicies sesión.\n\n"
            "Tocá **«Ir a Steam»** para continuar. El enlace vence en **10 minutos**."
        )
        assert "@everyone" not in reply["embed"].description
        assert reply["user_mentions"] is False
        row = reply["components"][0]
        link = row.add_link_button.call_args.args[0]
        assert len(link) <= 512
        payload = verify_steam_link_token(parse_qs(urlparse(link).query)["token"][0], "test_key")
        assert payload is not None
        assert payload["discord_id"] == str(user_id)
        assert "web_session_id" not in payload
        assert row.add_link_button.call_args.kwargs["label"] == "Ir a Steam"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Steam Name", None])
async def test_already_linked_is_private_terminal_state(client, name):
    client.model.api.get_player_by_discord.return_value = schemas.PlayerResponse(steam_id="76561198000000888", in_game_name=name, roles=[], created_at="2026-10-06T00:00:00Z", updated_at="2026-10-06T00:00:00Z")
    ev = event()
    await account.on_steam_link_button_click.metadata.callback(ev)
    reply = ev.interaction.edit_initial_response.call_args.kwargs
    assert reply["embed"].title == "Tu cuenta ya está vinculada"
    fields = {f.name: f.value for f in reply["embed"].fields}
    assert fields["Steam"] == (name or "tu cuenta de Steam")
    assert "Discord" in fields
    assert reply["embed"].description == "No tenés que hacer nada más."
    assert reply["components"] == []
    client.app.rest.build_message_action_row.assert_not_called()


@pytest.mark.asyncio
async def test_backend_failure_never_offers_link_or_leaks_details(client):
    client.model.api.get_player_by_discord.side_effect = Exception("secret-internal-error")
    ev = event()
    await account.on_steam_link_button_click.metadata.callback(ev)
    reply = ev.interaction.edit_initial_response.call_args.kwargs
    assert reply["embed"].title == "No pudimos generar tu enlace"
    assert "Probá de nuevo en unos minutos" in reply["embed"].description
    assert "secret-internal-error" not in reply["embed"].description
    assert reply["components"] == []


def test_panel_is_green_and_persistent(client):
    rest = MagicMock()
    embed, row = account.build_link_panel(rest)
    assert embed.title == "🔗 Vinculá tu cuenta de Steam | MATEFIELD"
    assert "1. Tocá **«Vincular mi cuenta de Steam»**" in embed.description
    assert "2. En la respuesta privada, tocá **«Ir a Steam»**" in embed.description
    assert "si tenés una membresía activa" in embed.description
    assert "rol de miembro verificado, si corresponde" in embed.description
    row.add_interactive_button.assert_called_once_with(
        hikari.ButtonStyle.SUCCESS, "btn_start_steam_link", label="Vincular mi cuenta de Steam", emoji=account.STEAM_LINK_EMOJI)


def test_link_length_does_not_depend_on_unicode_name_or_avatar(client):
    user = MagicMock(id=A, global_name="😀" * 32, username="long_username" * 3,
                     discriminator="0", display_avatar_url="https://cdn.discordapp.com/avatars/" + "a" * 150)
    link = account._build_user_steam_link(user, hikari.Snowflake(1552776537772920963))
    assert len(link) <= 512
    payload = verify_steam_link_token(parse_qs(urlparse(link).query)["token"][0], "test_key")
    assert payload is not None
    assert payload["discord_id"] == str(A)
    assert "discord_avatar" not in payload


def test_parse_steam_emoji_resilience():
    # Empty or None fallback
    assert account._parse_steam_emoji(None) == hikari.UnicodeEmoji("🎮")
    assert account._parse_steam_emoji("") == hikari.UnicodeEmoji("🎮")
    assert account._parse_steam_emoji("   ") == hikari.UnicodeEmoji("🎮")

    # Standard Unicode
    assert account._parse_steam_emoji("🎮") == hikari.UnicodeEmoji("🎮")

    # Standard Custom Emoji
    custom = account._parse_steam_emoji("<:steam:123456789012345678>")
    assert isinstance(custom, hikari.CustomEmoji)
    assert custom.id == 123456789012345678
    assert custom.name == "steam"

    # Unbracketed Custom Emoji
    unbracketed = account._parse_steam_emoji(":steam:123456789012345678")
    assert isinstance(unbracketed, hikari.CustomEmoji)
    assert unbracketed.id == 123456789012345678

    # Quoted Custom Emoji
    quoted = account._parse_steam_emoji('"<:steam:123456789012345678>"')
    assert isinstance(quoted, hikari.CustomEmoji)

    # Malformed bracketed mentions (e.g. placeholder or invalid mention from env)
    assert account._parse_steam_emoji("<EMOJI>") == hikari.UnicodeEmoji("🎮")
    assert account._parse_steam_emoji("<:steam:>") == hikari.UnicodeEmoji("🎮")

