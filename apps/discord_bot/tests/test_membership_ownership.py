"""The legacy bot keeps account and unrelated roles during the Laracord handover."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from wardogs_config import BOT_SETTINGS, DiscordBotSettings
from src.plugins import tasks, config

@pytest.fixture
def legacy_bot(monkeypatch):
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    model = MagicMock()
    model.api = AsyncMock()
    model.api.get_bot_configs.return_value = {"LINK_ROLE_ID": "9000"}
    model.api.sync_memberships.return_value = {
        "role_maps": {"REGULAR": 1001, "EXPRESS": 1002},
        "managed_special_roles": [2001, 3001, 3002],
        # Also protect a guild binding that is absent from the legacy role maps.
        "membership_managed_roles": [1001, 1002, 2001, 4001],
        "sync_data": [{"discord_id": "1111", "active_memberships": ["REGULAR"],
                       "special_roles": [2001, 3002, 4001]}],
    }
    app = MagicMock()
    app.rest = AsyncMock()
    app.cache.get_guilds_view.return_value = {10: MagicMock()}
    app.cache.get_roles_view_for_guild.return_value = {9000: MagicMock()}
    member = MagicMock()
    member.role_ids = [1002, 2001, 3001, 4001]
    app.cache.get_member.return_value = member
    monkeypatch.setattr(tasks.asyncio, "sleep", AsyncMock())
    return app, model


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [False, True])
async def test_membership_roles_stay_untouched_but_link_and_unrelated_roles_work(legacy_bot, single):
    app, model = legacy_bot
    if single:
        await tasks.sync_single_user_roles(app, model, 1111, target_guild_id=10)
    else:
        await tasks.execute_membership_sync(app, model, target_guild_id=10)
    model.api.sync_memberships.assert_awaited_once()
    app.rest.remove_role_from_member.assert_awaited_once_with(10, 1111, 3001)
    added = {call.args[2] for call in app.rest.add_role_to_member.await_args_list}
    assert added == {3002, 9000}


@pytest.mark.asyncio
async def test_unlink_removes_link_but_preserves_membership_roles(legacy_bot):
    app, model = legacy_bot
    model.api.sync_memberships.return_value["sync_data"] = []
    app.cache.get_member.return_value.role_ids = [1002, 2001, 4001, 9000]
    await tasks.sync_single_user_roles(app, model, 1111, target_guild_id=10)
    app.rest.remove_role_from_member.assert_awaited_once_with(10, 1111, 9000)
    app.rest.add_role_to_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_all_preserves_memberships_and_cleans_only_legacy_roles(legacy_bot, monkeypatch):
    app, model = legacy_bot
    model.api.get_player_by_discord.return_value = SimpleNamespace(steam_id="test-steam")
    model.api.get_bot_config.return_value = "9000"
    app.rest.fetch_member.return_value.role_ids = [1002, 2001, 4001, 3001, 9000]
    client = MagicMock(model=model, app=app)
    monkeypatch.setattr(config.plugin, "_client", client)
    command = config.RolesRemoveAll.metadata.owner()
    command.usuario = MagicMock(id=1111, mention="<@1111>")
    ctx = MagicMock(guild_id=10, app=app)
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    await command.callback(ctx)
    removed = {call.args[2] for call in app.rest.remove_role_from_member.await_args_list}
    assert removed == {3001, 9000}


@pytest.mark.asyncio
async def test_mvp_keeps_presence_but_does_not_create_legacy_membership(legacy_bot, monkeypatch):
    app, model = legacy_bot
    status = MagicMock(scoreCap=100, map="Ozeti", matchSeconds=0)
    status.scoreTick.current = 100
    status.rotation.nowIndex = 1
    model.api.get_status.return_value = status
    model.api.get_players.return_value.players = [MagicMock(kills=10, steamId="test-steam", name="MVP")]
    app.update_presence = AsyncMock()
    monkeypatch.setattr(tasks.plugin, "_client", MagicMock(model=model, app=app))
    await tasks.match_monitor.metadata.callback()
    model.api.add_membership.assert_not_awaited()
    model.api.broadcast.assert_not_awaited()
    app.update_presence.assert_awaited_once()


def test_older_api_fails_closed_for_special_badges(legacy_bot):
    _, model = legacy_bot
    payload = model.api.sync_memberships.return_value
    del payload["membership_managed_roles"]
    assert tasks.membership_roles_owned_by_laracord(payload) == {1001, 1002, 2001, 3001, 3002, 4001}


def test_membership_management_is_enabled_by_default_and_reads_the_environment(monkeypatch):
    monkeypatch.delenv("DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", raising=False)
    assert DiscordBotSettings(_env_file=None).DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED is True
    monkeypatch.setenv("DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", "false")
    assert DiscordBotSettings(_env_file=None).DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED is False

@pytest.mark.parametrize("enabled", [True, False])
def test_startup_registers_membership_plugin_only_for_legacy_owner(monkeypatch, enabled):
    import runpy
    from pathlib import Path
    import crescent
    import hikari

    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", enabled)
    monkeypatch.setattr(hikari, "GatewayBot", MagicMock())
    client = MagicMock()
    monkeypatch.setattr(crescent, "Client", MagicMock(return_value=client))
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "src/main.py"))
    client.plugins.load_folder.assert_called_once_with("src.plugins")
    if enabled:
        client.plugins.unload.assert_not_called()
    else:
        client.plugins.unload.assert_called_once_with("src.plugins.memberships")


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,command_name,option_name,method", [
    ("config", "GiveRole", "rol", "POST"),
    ("config", "RemoveRole", "rol", "DELETE"),
    ("database", "PlayerSetRole", "rol", "POST"),
    ("database", "PlayerRemoveRole", "rol", "DELETE"),
    ("database", "DbAddSpecialRole", "rol_especial", "POST"),
    ("database", "DbRemoveSpecialRole", "rol_especial", "DELETE"),
])
async def test_manual_role_commands_show_api_rejection_without_discord_sync(monkeypatch, module_name, command_name, option_name, method):
    from importlib import import_module
    from src.api_client import APIClient

    module = import_module(f"src.plugins.{module_name}")
    api = APIClient("http://api.test", "test-only")
    api.get_player_by_discord = AsyncMock(return_value=SimpleNamespace(steam_id="test-steam"))
    api.get_all_roles = AsyncMock(return_value=[{"code": "FOUNDER", "name": "Fundador",
                                               "role_type": "SPECIAL", "discord_role_id": "2001"}])
    response = MagicMock(status=409)
    response.json = AsyncMock(return_value={"detail": "Los roles de membresía se administran desde Laracord. Usá /membership."})
    request = MagicMock()
    request.__aenter__ = AsyncMock(return_value=response)
    request.__aexit__ = AsyncMock(return_value=False)
    http = MagicMock()
    http.request.return_value = request
    monkeypatch.setattr(api, "_get_session", AsyncMock(return_value=http))
    app = MagicMock()
    monkeypatch.setattr(module.plugin, "_client", MagicMock(model=MagicMock(api=api), app=app))
    sync = AsyncMock()
    monkeypatch.setattr(tasks, "sync_single_user_roles", sync)
    command = getattr(module, command_name).metadata.owner()
    command.usuario = MagicMock(id=1111, mention="<@1111>")
    setattr(command, option_name, "FOUNDER")
    ctx = MagicMock(guild_id=10, app=app)
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()

    await command.callback(ctx)

    assert http.request.call_args.args == (method, "http://api.test/api/v1/db/players/test-steam/roles/FOUNDER")
    ctx.respond.assert_awaited_once()
    reply = ctx.respond.await_args.args[0]
    assert reply.startswith("❌") and "Laracord" in reply and "/membership" in reply
    assert "✅" not in reply
    sync.assert_not_awaited()
    app.rest.add_role_to_member.assert_not_called()
    app.rest.remove_role_from_member.assert_not_called()


@pytest.mark.asyncio
async def test_membership_handover_disables_expiration_notices_before_api_or_discord(legacy_bot, monkeypatch):
    app, model = legacy_bot
    monkeypatch.setattr(tasks.plugin, "_client", MagicMock(model=model, app=app))

    await tasks.expiration_notifier_task.metadata.callback()

    model.api.get_expiring_memberships.assert_not_awaited()
    model.api.mark_membership_notified.assert_not_awaited()
    app.rest.fetch_user.assert_not_awaited()
    app.rest.create_dm_channel.assert_not_awaited()
    app.rest.create_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabled_legacy_management_preserves_both_expiration_notices(legacy_bot, monkeypatch):
    app, model = legacy_bot
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", True)
    monkeypatch.setattr(tasks.plugin, "_client", MagicMock(model=model, app=app))
    model.api.get_expiring_memberships.return_value = {
        "expiring_3d": [{"id": 11, "discord_id": "1111", "type": "REGULAR"}],
        "expiring_24h": [{"id": 12, "discord_id": "2222", "type": "EXPRESS"}],
    }
    user = MagicMock()
    user.send = AsyncMock()
    app.rest.fetch_user.return_value = user

    await tasks.expiration_notifier_task.metadata.callback()

    model.api.get_expiring_memberships.assert_awaited_once()
    assert [call.args[0] for call in app.rest.fetch_user.await_args_list] == [1111, 2222]
    assert user.send.await_count == 2
    model.api.mark_membership_notified.assert_any_await(11, "3d")
    model.api.mark_membership_notified.assert_any_await(12, "24h")
