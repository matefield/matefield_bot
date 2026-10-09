from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.api_client import APIClient
from src.plugins.memberships import build_player_memberships_view
from wardogs_schemas import dtos as schemas


def test_build_player_memberships_view_all_fields():
    app_mock = MagicMock()
    app_mock.rest.build_message_action_row.return_value = MagicMock()

    memberships_data = [
        {
            "id": 42,
            "steam_id": "76561198000000001",
            "type": "VIP_COMUN",
            "is_active": True,
            "start_date": "2026-09-01T12:00:00+00:00",
            "end_date": "2026-10-01T12:00:00+00:00",
            "special_role": "ADMIN",
            "special_role_id": 999999,
            "rcon_sync_status": "SUCCESS"
        }
    ]

    embed, components = build_player_memberships_view(
        app_mock,
        usuario_id=123456789,
        memberships=memberships_data,
        page=1,
        total=1,
        limit=5
    )

    assert embed.title is not None and "Historial de Membresías" in embed.title
    assert len(embed.fields) == 1
    field = embed.fields[0]

    # Verify that all table fields are rendered in the field
    assert "Membresía #42" in field.name
    assert "VIP_COMUN" in field.name
    assert "🟢 Activa" in field.value
    assert "is_active=True" in field.value
    assert "76561198000000001" in field.value
    assert "2026-09-01 12:00:00" in field.value
    assert "2026-10-01 12:00:00" in field.value
    assert "999999" in field.value
    assert "SUCCESS" in field.value


@pytest.mark.asyncio
async def test_api_client_get_paginated_memberships_url(monkeypatch):
    client = APIClient("http://test-server", "secret-key")

    requested_url: str | None = None

    async def mock_request(method, endpoint, **kwargs):
        nonlocal requested_url
        requested_url = endpoint
        return {"page": 1, "limit": 5, "total": 0, "memberships": []}

    monkeypatch.setattr(client, "_request", mock_request)

    res = await client.get_paginated_memberships(page=2, limit=5, discord_id="123456")
    assert requested_url is not None and "/api/v1/db/memberships?page=2&limit=5&discord_id=123456" in requested_url
    assert res["memberships"] == []


@pytest.mark.asyncio
async def test_role_set_link_retroactive_grant():
    from src.plugins.config import RoleSetLink, plugin

    ctx = MagicMock()
    ctx.guild_id = 987654321
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()

    mock_role = MagicMock()
    mock_role.id = 112233
    mock_role.is_managed = False

    cmd = RoleSetLink.metadata.owner()
    cmd.rol = mock_role

    mock_member_1 = MagicMock()
    mock_member_1.role_ids = [445566]
    mock_member_1.add_role = AsyncMock()

    mock_member_2 = MagicMock()
    mock_member_2.role_ids = [112233]  # already had it
    mock_member_2.add_role = AsyncMock()

    def get_member(guild_id, user_id):
        if user_id == 1001:
            return mock_member_1
        if user_id == 1002:
            return mock_member_2
        return None

    plugin._client = MagicMock()
    plugin._client.app.cache.get_member.side_effect = get_member
    plugin._client.model.api.set_bot_config = AsyncMock()
    plugin._client.model.api.get_paginated_players = AsyncMock(return_value={
        "total": 2,
        "page": 1,
        "limit": 100,
        "players": [
            {"steam_id": "s1", "discord_id": "1001"},
            {"steam_id": "s2", "discord_id": "1002"}
        ]
    })

    ctx.edit = AsyncMock()

    task = await cmd.callback(ctx)
    if task:
        await task

    plugin._client.model.api.set_bot_config.assert_any_call("LINK_ROLE_ID", "112233")
    plugin._client.model.api.set_bot_config.assert_any_call("GUILD_ID", "987654321")
    mock_member_1.add_role.assert_called_once_with(112233, reason="Rol de vinculación asignado retroactivamente (/role set_link)")
    mock_member_2.add_role.assert_not_called()
    ctx.respond.assert_called_once()
    assert "Rol de vinculación configurado" in ctx.respond.call_args[0][0]
    ctx.edit.assert_called_once()
    edit_text = ctx.edit.call_args[1]["content"]
    assert "1 rol(es) asignado(s)" in edit_text
    assert "1 ya lo tenían" in edit_text


@pytest.mark.asyncio
async def test_roles_set_link_plural_command_alias():
    from src.plugins.config import RolesSetLink, plugin

    ctx = MagicMock()
    ctx.guild_id = 123456
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()

    mock_role = MagicMock()
    mock_role.id = 887766
    mock_role.is_managed = False

    cmd = RolesSetLink.metadata.owner()
    cmd.rol = mock_role

    plugin._client = MagicMock()
    plugin._client.model.api.set_bot_config = AsyncMock()
    plugin._client.model.api.get_paginated_players = AsyncMock(return_value={"total": 0, "players": []})

    with patch("src.plugins.config._sync_retroactive_link_role", new=AsyncMock(return_value=(0, 0))):
        await cmd.callback(ctx)

    plugin._client.model.api.set_bot_config.assert_any_call("LINK_ROLE_ID", "887766")
    plugin._client.model.api.set_bot_config.assert_any_call("GUILD_ID", "123456")
    ctx.respond.assert_called_once()
    assert "Rol de vinculación configurado" in ctx.respond.call_args[0][0]


@pytest.mark.asyncio
async def test_unlink_account_permissions():
    from src.hooks import admin_only
    from src.plugins.account import UnlinkAccount, plugin

    cmd_cls = UnlinkAccount.metadata.owner
    hooks = UnlinkAccount.metadata.hooks
    assert admin_only in hooks, "UnlinkAccount must have admin_only hook"

    # 1. Admin unlinking someone else -> success
    cmd_admin = cmd_cls()
    target_user = MagicMock()
    target_user.id = 8888
    target_user.mention = "<@8888>"
    cmd_admin.usuario = target_user

    ctx_admin = MagicMock()
    ctx_admin.guild_id = None
    ctx_admin.user.id = 1111
    ctx_admin.defer = AsyncMock()
    ctx_admin.respond = AsyncMock()

    plugin._client = MagicMock()
    plugin._client.model.api.unlink_account = AsyncMock()

    await cmd_admin.callback(ctx_admin)
    plugin._client.model.api.unlink_account.assert_called_once_with("8888")
    assert "ha sido desvinculada" in ctx_admin.respond.call_args[0][0]

    # 2. Admin unlinking themselves (no usuario) -> success
    cmd_self = cmd_cls()
    cmd_self.usuario = None

    ctx_self = MagicMock()
    ctx_self.guild_id = None
    ctx_self.user.id = 1234
    ctx_self.defer = AsyncMock()
    ctx_self.respond = AsyncMock()

    plugin._client.model.api.unlink_account = AsyncMock()

    await cmd_self.callback(ctx_self)
    plugin._client.model.api.unlink_account.assert_called_once_with("1234")
    assert "Tu cuenta de Discord ha sido desvinculada" in ctx_self.respond.call_args[0][0]


@pytest.mark.asyncio
async def test_player_link_without_params(monkeypatch):
    from src.plugins.account import LinkAccount, plugin

    cmd_cls = LinkAccount.metadata.owner
    cmd = cmd_cls()
    cmd.steam_id = None
    cmd.usuario = None

    ctx = MagicMock()
    ctx.user.id = 111222333
    ctx.user.mention = "<@111222333>"
    ctx.guild_id = 999888
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()

    mock_row = MagicMock()
    ctx.app.rest.build_message_action_row.return_value = mock_row

    plugin._client = MagicMock()
    plugin._client.model.api.api_key = "test_key"
    plugin._client.model.api.get_player_by_discord = AsyncMock(return_value=None)
    ctx.user.username = "Test user"
    ctx.user.global_name = None
    plugin._client.model.public_api_url = "http://test-server:8000"

    await cmd.callback(ctx)

    ctx.respond.assert_called_once()
    kwargs = ctx.respond.call_args[1]
    assert kwargs.get("ephemeral") is True
    assert "embed" in kwargs
    assert kwargs["embed"].title == "Vinculá tu cuenta de Steam"
    mock_row.add_link_button.assert_called_once()
    link_url = mock_row.add_link_button.call_args[0][0]
    assert "http://test-server:8000/api/v1/auth/steam/login?token=" in link_url


@pytest.mark.asyncio
async def test_player_link_with_params_restricted(monkeypatch):
    from src.plugins.account import LinkAccount

    cmd_cls = LinkAccount.metadata.owner
    cmd = cmd_cls()
    cmd.steam_id = "76561198000000001"
    cmd.usuario = None

    ctx = MagicMock()
    ctx.user.id = 111222333
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()

    # Non-admin
    monkeypatch.setattr("src.plugins.account.check_is_admin", AsyncMock(return_value=False))

    await cmd.callback(ctx)

    ctx.respond.assert_called_once()
    msg = ctx.respond.call_args[0][0]
    assert "La vinculación manual con Steam ID está reservada para administradores" in msg


@pytest.mark.asyncio
async def test_player_link_with_params_admin_triggers_sync(monkeypatch):
    from src.plugins.account import LinkAccount, plugin

    cmd_cls = LinkAccount.metadata.owner
    cmd = cmd_cls()
    cmd.steam_id = "76561198000000001"
    target_user = MagicMock()
    target_user.id = 5555
    target_user.mention = "<@5555>"
    cmd.usuario = target_user

    ctx = MagicMock()
    ctx.guild_id = 999
    ctx.user.id = 111
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()

    plugin._client = MagicMock()
    plugin._client.model.api.link_account = AsyncMock()
    mock_sync = AsyncMock()
    monkeypatch.setattr("src.plugins.account.sync_single_user_roles", mock_sync)
    monkeypatch.setattr("src.plugins.account.check_is_admin", AsyncMock(return_value=True))

    await cmd.callback(ctx)

    plugin._client.model.api.link_account.assert_awaited_once_with("5555", "76561198000000001")
    mock_sync.assert_awaited_once_with(ctx.app, plugin.model, 5555, 999)
    ctx.respond.assert_called_once()
    assert "Has vinculado a <@5555>" in ctx.respond.call_args[0][0]



@pytest.mark.asyncio
async def test_player_link_channel_admin(monkeypatch):
    from src.plugins.account import LinkChannel, plugin

    cmd_cls = LinkChannel.metadata.owner
    cmd = cmd_cls()
    cmd.canal = None

    ctx = MagicMock()
    ctx.channel_id = 444555666
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    ctx.app.rest.create_message = AsyncMock()

    mock_row = MagicMock()
    ctx.app.rest.build_message_action_row.return_value = mock_row

    plugin._client = MagicMock()
    plugin._client.model.api.get_bot_config = AsyncMock(return_value=None)
    plugin._client.model.api.set_bot_config = AsyncMock()
    plugin._client.model.public_api_url = "http://test-server:8000"

    monkeypatch.setattr("src.plugins.account.check_is_admin", AsyncMock(return_value=True))

    await cmd.callback(ctx)

    ctx.app.rest.create_message.assert_called_once()
    target_channel = ctx.app.rest.create_message.call_args[0][0]
    assert target_channel == 444555666
    mock_row.add_interactive_button.assert_called_once()
    assert mock_row.add_interactive_button.call_args[0][1] == "btn_start_steam_link"
    assert "Panel de vinculación publicado exitosamente" in ctx.respond.call_args[0][0]


@pytest.mark.asyncio
async def test_player_link_channel_updates_pinned_panel_in_place(monkeypatch):
    from src.plugins.account import LinkChannel, plugin

    cmd = LinkChannel.metadata.owner()
    cmd.canal = None
    ctx = MagicMock()
    ctx.channel_id = 444555666
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    ctx.app.rest.edit_message = AsyncMock(return_value=MagicMock(id=123456789))
    ctx.app.rest.create_message = AsyncMock()
    plugin._client = MagicMock()
    plugin._client.model.public_api_url = "http://test-server:8000"
    plugin._client.model.api.get_bot_config = AsyncMock(side_effect=["444555666", "123456789"])
    plugin._client.model.api.set_bot_config = AsyncMock()
    monkeypatch.setattr("src.plugins.account.check_is_admin", AsyncMock(return_value=True))

    await cmd.callback(ctx)

    ctx.app.rest.edit_message.assert_awaited_once()
    ctx.app.rest.create_message.assert_not_awaited()
    components = ctx.app.rest.edit_message.call_args.kwargs["components"]
    components[0].add_interactive_button.assert_called_once()
    assert components[0].add_interactive_button.call_args[0][1] == "btn_start_steam_link"


@pytest.mark.asyncio
async def test_player_profile_admin_vs_player(monkeypatch):
    from src.plugins.account import Profile, plugin

    cmd_cls = Profile.metadata.owner
    
    player_data = {
        "steam_id": "76561198058686447",
        "in_game_name": "Fr4nc0",
        "discord_id": "111222333",
        "role": "VIP",
        "roles": ["Fundador"],
        "observations": "Notas privadas de staff",
        "active_memberships": [{"type": "VIP_COMUN", "end_time": "2026-11-10T03:00:00+00:00"}]
    }

    plugin._client = MagicMock()
    plugin._client.model.api.get_player_by_discord = AsyncMock(return_value=schemas.PlayerResponse(steam_id="76561198058686447", in_game_name="Player", roles=[], created_at="2026-10-06T00:00:00Z", updated_at="2026-10-06T00:00:00Z"))
    player_data["created_at"] = "2026-10-06T00:00:00Z"
    player_data["updated_at"] = "2026-10-06T00:00:00Z"
    plugin._client.model.api.get_player_by_steam = AsyncMock(return_value=schemas.PlayerResponse.model_validate(player_data))
    plugin._client.model.api.get_player_historical_stats = AsyncMock(return_value={
        "matches_played": 10, "total_kills": 20, "total_deaths": 5, "total_cash": 1000
    })

    # 1. Non-admin user querying profile (self)
    cmd = cmd_cls()
    cmd.usuario = None
    cmd.steam_id = None
    ctx = MagicMock()
    ctx.user.id = 111222333
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()

    monkeypatch.setattr("src.plugins.account.check_is_admin", AsyncMock(return_value=False))

    await cmd.callback(ctx)

    ctx.respond.assert_called_once()
    embed = ctx.respond.call_args[1]["embed"]
    field_names = [f.name for f in embed.fields]
    assert "⭐ Rango RCON" not in field_names
    assert "📝 Observaciones Internas" not in field_names
    assert "🏷️ Roles Especiales" in field_names
    special_field = next(f for f in embed.fields if f.name == "🏷️ Roles Especiales")
    assert "Fundador" in special_field.value

    # 2. Admin querying profile
    ctx.respond.reset_mock()
    monkeypatch.setattr("src.plugins.account.check_is_admin", AsyncMock(return_value=True))

    await cmd.callback(ctx)

    ctx.respond.assert_called_once()
    embed_admin = ctx.respond.call_args[1]["embed"]
    admin_field_names = [f.name for f in embed_admin.fields]
    assert "⭐ Rango RCON" in admin_field_names
    assert "📝 Observaciones Internas" in admin_field_names
    rcon_field = next(f for f in embed_admin.fields if f.name == "⭐ Rango RCON")
    assert rcon_field.value == "VIP"
    obs_field = next(f for f in embed_admin.fields if f.name == "📝 Observaciones Internas")
    assert "Notas privadas de staff" in obs_field.value


@pytest.mark.asyncio
async def test_membership_sync_command(monkeypatch):
    from src.plugins.memberships import ForceSyncMemberships, plugin
    
    cmd_cls = ForceSyncMemberships.metadata.owner
    cmd = cmd_cls()
    
    ctx = MagicMock()
    ctx.guild_id = 999
    ctx.app = MagicMock()
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    plugin._client = MagicMock()

    mock_stats = {
        "success": True,
        "active_rcon_slots": 141,
        "expired_count": 2,
        "users_checked": 50,
        "roles_added": 3,
        "roles_removed": 1,
        "whitelist_skipped": 1
    }
    
    monkeypatch.setattr(
        "src.plugins.tasks.execute_membership_sync",
        AsyncMock(return_value=mock_stats)
    )

    await cmd.callback(ctx)

    ctx.defer.assert_called_once()
    ctx.respond.assert_called_once()
    embed = ctx.respond.call_args[1]["embed"]
    assert "Sincronización Completa" in embed.title
    field_names = [f.name for f in embed.fields]
    assert "🎮 Slots Reservados RCON" in field_names
    assert "⏰ Membresías Expiradas" in field_names
    assert "➕ Roles Añadidos" in field_names
    assert "➖ Roles Removidos" in field_names
    assert "🛡️ Whitelist" in field_names


@pytest.mark.asyncio
async def test_rewards_plugin_commands():
    from src.plugins.rewards import (
        RewardsAddItem,
        RewardsBalance,
        RewardsCatalog,
        RewardsClaim,
        RewardsDeliverClaim,
        RewardsGivePoints,
        RewardsRefundClaim,
        RewardsSetRate,
        RewardsSetThreshold,
        RewardsVerifyClaim,
    )
    from src.plugins.rewards import (
        plugin as rewards_plugin,
    )

    mock_api = MagicMock()
    mock_api.get_player_rewards_balance = AsyncMock(return_value=schemas.PlayerRewardBalanceResponse(
        steam_id="76561198000000001",
        discord_id="123456",
        in_game_name="ProGamer",
        reward_points=75,
        total_seeding_minutes=150,
        active_claims=[schemas.RewardClaimResponse(id=1, steam_id="76561198000000001", reward_name="Key Game", claim_code="MF-AAAA-BBBB", status="PENDING", reward_code="STEAM_KEY", points_spent=100, claimed_at="2026-10-06T00:00:00Z")]
    ))
    mock_api.get_rewards_catalog = AsyncMock(return_value=[ schemas.RewardItemResponse(id=1, code="VIP_MONTH", name="VIP 30d", cost_points=60, delivery_type="AUTOMATIC", description="Acceso VIP", reward_type="VIP", reward_value="1", is_active=True), schemas.RewardItemResponse(id=2, code="STEAM_KEY", name="Key Game", cost_points=100, delivery_type="MANUAL_TICKET", description="Ticket key", reward_type="KEY", reward_value="key", is_active=True) ])
    mock_api.claim_reward = AsyncMock(return_value=schemas.RewardClaimResultResponse(
        ok=True,
        claim_code="MF-1111-2222",
        reward_name="VIP 30d",
        cost_points=60,
        remaining_points=15,
        delivery=schemas.RewardClaimDeliveryInfo(delivery_type="AUTOMATIC"),
        status="PENDING",
        reward_code="VIP_MONTH"
    ))
    mock_api.set_bot_config = AsyncMock(return_value={"ok": True})
    mock_api.verify_reward_claim = AsyncMock(return_value={
        "claim_code": "MF-1111-2222",
        "status": "PENDING",
        "reward_code": "STEAM_KEY",
        "reward_name": "Key Game",
        "points_spent": 100,
        "steam_id": "76561198000000001",
        "discord_id": "123456",
        "claimed_at": "2026-09-27T12:00:00"
    })
    mock_api.deliver_reward_claim = AsyncMock(return_value={"ok": True, "message": "Entregado"})
    mock_api.refund_reward_claim = AsyncMock(return_value={"ok": True, "message": "Reembolsado"})
    mock_api.give_reward_points = AsyncMock(return_value={"ok": True, "steam_id": "76561198000000001", "new_balance": 125})
    mock_api.create_or_update_reward_item = AsyncMock(return_value={"ok": True, "message": "Item creado"})

    rewards_plugin._client = MagicMock()
    rewards_plugin.model.api = mock_api

    ctx = MagicMock()
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    ctx.user = MagicMock(id=123456, mention="<@123456>")

    # 1. Test /rewards balance
    bal_cmd = RewardsBalance.metadata.owner()
    bal_cmd.usuario = None
    await bal_cmd.callback(ctx)
    mock_api.get_player_rewards_balance.assert_awaited_with("123456")
    embed = ctx.respond.call_args[1]["embed"]
    assert "Centro de Recompensas" in embed.title

    # 2. Test /rewards catalog
    cat_cmd = RewardsCatalog.metadata.owner()
    ctx.reset_mock()
    await cat_cmd.callback(ctx)
    mock_api.get_rewards_catalog.assert_awaited_with(only_active=True)
    embed = ctx.respond.call_args[1]["embed"]
    assert "Catálogo de Recompensas" in embed.title

    # 3. Test /rewards claim
    claim_cmd = RewardsClaim.metadata.owner()
    claim_cmd.recompensa = "VIP_MONTH"
    ctx.reset_mock()
    await claim_cmd.callback(ctx)
    mock_api.claim_reward.assert_awaited_with("123456", "VIP_MONTH")
    embed = ctx.respond.call_args[1]["embed"]
    assert "Canje Exitoso" in embed.title

    # 4. Test /rewards admin set_threshold
    thresh_cmd = RewardsSetThreshold.metadata.owner()
    thresh_cmd.limite = 25
    ctx.reset_mock()
    await thresh_cmd.callback(ctx)
    mock_api.set_bot_config.assert_awaited_with("SEEDING_MIN_PLAYERS", "25")

    # 5. Test /rewards admin set_rate
    rate_cmd = RewardsSetRate.metadata.owner()
    rate_cmd.minutos = 45
    ctx.reset_mock()
    await rate_cmd.callback(ctx)
    mock_api.set_bot_config.assert_awaited_with("SEEDING_MINUTES_PER_POINT", "45")

    # 6. Test /rewards admin verify
    verify_cmd = RewardsVerifyClaim.metadata.owner()
    verify_cmd.codigo_canje = "MF-1111-2222"
    ctx.reset_mock()
    await verify_cmd.callback(ctx)
    mock_api.verify_reward_claim.assert_awaited_with("MF-1111-2222")

    # 7. Test /rewards admin deliver
    deliver_cmd = RewardsDeliverClaim.metadata.owner()
    deliver_cmd.codigo_canje = "MF-1111-2222"
    deliver_cmd.notas = "Entregado en ticket #12"
    ctx.reset_mock()
    await deliver_cmd.callback(ctx)
    mock_api.deliver_reward_claim.assert_awaited_with("MF-1111-2222", delivered_by=str(ctx.user), notes="Entregado en ticket #12")

    # 8. Test /rewards admin refund
    refund_cmd = RewardsRefundClaim.metadata.owner()
    refund_cmd.codigo_canje = "MF-1111-2222"
    refund_cmd.motivo = "Sin stock"
    ctx.reset_mock()
    await refund_cmd.callback(ctx)
    mock_api.refund_reward_claim.assert_awaited_with("MF-1111-2222", refunded_by=str(ctx.user), reason="Sin stock")

    # 9. Test /rewards admin give_points
    give_cmd = RewardsGivePoints.metadata.owner()
    give_cmd.usuario = None
    give_cmd.steam_id = "76561198000000001"
    give_cmd.puntos = 50
    give_cmd.motivo = "Evento de navidad"
    ctx.reset_mock()
    await give_cmd.callback(ctx)
    mock_api.give_reward_points.assert_awaited_with("76561198000000001", 50, "Evento de navidad")

    # 10. Test /rewards admin add_item
    add_cmd = RewardsAddItem.metadata.owner()
    add_cmd.codigo = "VIP_15D"
    add_cmd.nombre = "VIP 15 Días"
    add_cmd.costo = 30
    add_cmd.tipo_entrega = "AUTOMATIC"
    add_cmd.tipo_recompensa = "MEMBERSHIP"
    add_cmd.valor = "VIP"
    add_cmd.duracion_dias = 15
    add_cmd.descripcion = "Membresía corta"
    ctx.reset_mock()
    await add_cmd.callback(ctx)
    mock_api.create_or_update_reward_item.assert_awaited_with(
        code="VIP_15D",
        name="VIP 15 Días",
        cost_points=30,
        delivery_type="AUTOMATIC",
        reward_type="MEMBERSHIP",
        reward_value="VIP",
        duration_days=15,
        description="Membresía corta",
        is_active=True,
    )




