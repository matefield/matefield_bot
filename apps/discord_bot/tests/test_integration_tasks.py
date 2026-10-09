from unittest.mock import AsyncMock, MagicMock

import pytest
from src.plugins.tasks import execute_membership_sync, membership_monitor, plugin


@pytest.mark.asyncio
async def test_membership_monitor_syncs_roles_and_respects_whitelist():
    mock_api = AsyncMock()
    mock_app = MagicMock()
    mock_app.cache = MagicMock()
    mock_app.rest = AsyncMock()

    mock_api.sync_memberships.return_value = {
        "sync_data": [
            {
                "discord_id": "111111",
                "active_memberships": ["VIP_COMUN"],
                "special_roles": []
            },
            {
                "discord_id": "222222", # Whitelisted
                "active_memberships": [],
                "special_roles": []
            }
        ],
        "role_maps": {"VIP_COMUN": 5001, "VIP_PRO": 5002},
        "managed_special_roles": []
    }

    mock_api.get_bot_configs.return_value = {
        "SYNC_WHITELIST": "222222",
        "LINK_ROLE_ID": "9999",
        "BAN_ROLE_DEFAULT": "8888"
    }

    mock_app.cache.get_guilds_view.return_value = {10: MagicMock()}
    mock_app.cache.get_roles_view_for_guild.return_value = {5001: MagicMock(), 5002: MagicMock()}

    # Member 111111 currently has expired VIP_PRO (5002), needs VIP_COMUN (5001)
    member_1 = MagicMock()
    member_1.role_ids = [5002, 9999] # 9999 is LINK_ROLE_ID
    mock_app.cache.get_member.return_value = member_1

    mock_client = MagicMock()
    mock_client.model = MagicMock()
    mock_client.model.api = mock_api
    mock_client.app = mock_app

    orig_client = getattr(plugin, "_client", None)
    try:
        plugin._client = mock_client

        await membership_monitor.metadata.callback()

        mock_api.sync_memberships.assert_called_once()
        # Expired role 5002 removed
        mock_app.rest.remove_role_from_member.assert_called_once_with(10, 111111, 5002)
        # Active role 5001 added
        mock_app.rest.add_role_to_member.assert_called_once_with(10, 111111, 5001)
        # Link role 9999 was NOT removed
        for call_args in mock_app.rest.remove_role_from_member.call_args_list:
            assert call_args[0][2] != 9999
    finally:
        plugin._client = orig_client


def test_format_match_presence_smart_contextual():
    from src.plugins.tasks import format_match_presence, get_next_map

    # Test get_next_map resolution
    assert get_next_map("Bakurani") == "Ozeti"
    assert get_next_map("Ozeti") == "Zestafona"
    assert get_next_map("Zestafona") == "Bakurani"

    # 1. Error / None status (no emojis)
    s_none = format_match_presence(None)
    assert s_none == "Mantenimiento / Reiniciando"
    assert len(s_none) <= 35

    # 2. Match ended mentions next map (no MVP, no emojis)
    s_obj = MagicMock(map="Bakurani", rotation=None)
    s_ended = format_match_presence(s_obj, match_ended=True)
    assert s_ended == "Fin: Bakurani | Prox: Ozeti"
    assert len(s_ended) <= 35

    # 3. Server empty (0 players -> 0/100, no emojis)
    s_empty = MagicMock(
        map="Bakurani",
        players=MagicMock(current=0, max=100),
        factionScores=[],
        scoreCap=100,
        scoreTick=MagicMock(current=0)
    )
    res_empty = format_match_presence(s_empty)
    assert res_empty == "Bakurani 0/100"
    assert len(res_empty) <= 35

    # 4. Low players waiting (< 15 -> cur/max, no emojis)
    s_waiting = MagicMock(
        map="Bakurani",
        players=MagicMock(current=6, max=100),
        factionScores=[],
        scoreCap=100,
        scoreTick=MagicMock(current=0)
    )
    res_waiting = format_match_presence(s_waiting)
    assert res_waiting == "Bakurani 6/100"
    assert len(res_waiting) <= 35

    # 5. Active combat with 3 factions (Lonestar, Valkyra, Manticore)
    s_combat = MagicMock(
        map="Bakurani",
        players=MagicMock(current=80, max=100),
        factionScores=[
            {"name": "Lonestar", "score": 45},
            {"name": "Valkyre", "score": 32},
            {"name": "Manticore", "score": 28},
        ],
        scoreCap=100,
        scoreTick=MagicMock(current=45)
    )
    res_combat = format_match_presence(s_combat)
    assert res_combat == "Bakurani [80/100] L45 V32 M28"
    assert len(res_combat) <= 35

    # 6. High scores in active match formatted as normal combat (no [Final] tag)
    s_climax = MagicMock(
        map="Bakurani",
        players=MagicMock(current=100, max=100),
        factionScores=[
            {"name": "Lonestar", "score": 92},
            {"name": "Valkyre", "score": 88},
            {"name": "Manticore", "score": 75},
        ],
        scoreCap=100,
        scoreTick=MagicMock(current=92)
    )
    res_climax = format_match_presence(s_climax)
    assert res_climax == "Bakurani [100/100] L92 V88 M75"
    assert len(res_climax) <= 35

    # 7. Server Full (shows 100/100, no emojis)
    s_full = MagicMock(
        map="Bakurani",
        players=MagicMock(current=100, max=100),
        factionScores=[
            {"name": "Lonestar", "score": 40},
            {"name": "Valkyre", "score": 35},
            {"name": "Manticore", "score": 30},
        ],
        scoreCap=100,
        scoreTick=MagicMock(current=40)
    )
    res_full = format_match_presence(s_full)
    assert res_full == "Bakurani [100/100] L40 V35 M30"
    assert len(res_full) <= 35

    s_full_warmup = MagicMock(
        map="Bakurani",
        players=MagicMock(current=100, max=100),
        factionScores=[],
        scoreCap=100,
        scoreTick=MagicMock(current=0)
    )
    res_full_warmup = format_match_presence(s_full_warmup)
    assert res_full_warmup == "Bakurani 100/100"
    assert len(res_full_warmup) <= 35

    # 8. Super long map name capped strictly at 35 chars
    s_long_map = MagicMock(
        map="SuperLongDangerousSectorBattlegroundMap",
        players=MagicMock(current=100, max=100),
        factionScores=[
            {"name": "Lonestar", "score": 99},
            {"name": "Valkyre", "score": 95},
            {"name": "Manticore", "score": 90},
        ],
        scoreCap=100,
        scoreTick=MagicMock(current=99)
    )
    res_long = format_match_presence(s_long_map)
    assert len(res_long) <= 35


@pytest.mark.asyncio
async def test_execute_membership_sync_grants_link_role_to_linked_users():
    app = MagicMock()
    app.cache = MagicMock()
    app.rest = AsyncMock()

    guild_id = 999
    discord_id = 12345
    link_role_id = 7788

    app.cache.get_guilds_view.return_value = {guild_id: MagicMock()}
    app.cache.get_roles_view_for_guild.return_value = {link_role_id: MagicMock()}

    member = MagicMock()
    member.role_ids = []  # Missing link role
    app.cache.get_member.return_value = member

    model = MagicMock()
    model.api = AsyncMock()
    model.api.sync_memberships.return_value = {
        "sync_data": [
            {"discord_id": str(discord_id), "active_memberships": [], "special_roles": []}
        ],
        "role_maps": {},
        "managed_special_roles": [],
        "expired_count": 0,
        "active_rcon_slots": 0,
    }
    model.api.get_bot_configs.return_value = {
        "LINK_ROLE_ID": str(link_role_id)
    }

    stats = await execute_membership_sync(app, model, target_guild_id=guild_id)

    assert stats["success"] is True
    assert stats["roles_added"] == 1
    app.rest.add_role_to_member.assert_called_once_with(guild_id, discord_id, link_role_id)


@pytest.mark.asyncio
async def test_sync_single_user_roles_linked():
    from src.plugins.tasks import sync_single_user_roles

    app = MagicMock()
    app.cache = MagicMock()
    app.rest = AsyncMock()

    guild_id = 100
    discord_id = 5555
    link_role_id = 9001
    vip_role_id = 9002
    old_role_id = 9003

    member = MagicMock()
    member.role_ids = [old_role_id]  # Has old managed role, lacks link and vip roles
    app.cache.get_member.return_value = member

    model = MagicMock()
    model.api = AsyncMock()
    model.api.get_bot_configs.return_value = {
        "LINK_ROLE_ID": str(link_role_id),
        "SYNC_WHITELIST": ""
    }
    model.api.sync_memberships.return_value = {
        "sync_data": [
            {
                "discord_id": str(discord_id),
                "active_memberships": ["VIP_PRO"],
                "special_roles": []
            }
        ],
        "role_maps": {"VIP_PRO": vip_role_id},
        "managed_special_roles": [old_role_id]
    }

    res = await sync_single_user_roles(app, model, discord_id, target_guild_id=guild_id)

    assert res.get("success", False) is True
    assert res["added"] == 2  # Link role + VIP role
    assert res["removed"] == 1  # Old role removed
    app.rest.remove_role_from_member.assert_called_once_with(guild_id, discord_id, old_role_id)
    assert app.rest.add_role_to_member.call_count == 2
    added_roles = {call[0][2] for call in app.rest.add_role_to_member.call_args_list}
    assert added_roles == {link_role_id, vip_role_id}


@pytest.mark.asyncio
async def test_sync_single_user_roles_unlinked_revokes_all():
    from src.plugins.tasks import sync_single_user_roles

    app = MagicMock()
    app.cache = MagicMock()
    app.rest = AsyncMock()

    guild_id = 100
    discord_id = 7777
    link_role_id = 9001
    vip_role_id = 9002

    member = MagicMock()
    member.role_ids = [link_role_id, vip_role_id]  # Currently has both roles
    app.cache.get_member.return_value = member

    model = MagicMock()
    model.api = AsyncMock()
    model.api.get_bot_configs.return_value = {
        "LINK_ROLE_ID": str(link_role_id),
        "SYNC_WHITELIST": ""
    }
    # User 7777 is not in sync_data (unlinked)
    model.api.sync_memberships.return_value = {
        "sync_data": [],
        "role_maps": {"VIP_PRO": vip_role_id},
        "managed_special_roles": []
    }

    res = await sync_single_user_roles(app, model, discord_id, target_guild_id=guild_id)

    assert res.get("success", False) is True
    assert res["added"] == 0
    assert res["removed"] == 2
    removed_roles = {call[0][2] for call in app.rest.remove_role_from_member.call_args_list}
    assert removed_roles == {link_role_id, vip_role_id}


@pytest.mark.asyncio
async def test_sync_single_user_roles_respects_whitelist():
    from src.plugins.tasks import sync_single_user_roles

    app = MagicMock()
    model = MagicMock()
    model.api = AsyncMock()
    model.api.get_bot_configs.return_value = {
        "SYNC_WHITELIST": "9999"
    }

    res = await sync_single_user_roles(app, model, 9999, target_guild_id=100)

    assert res.get("success", False) is True
    assert res.get("whitelist_skipped") is True
    model.api.sync_memberships.assert_not_called()



