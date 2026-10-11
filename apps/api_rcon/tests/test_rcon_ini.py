import pytest
from src.connections.apis.rcon import _update_ini_array


def test_update_ini_array_creates_section_when_missing():
    initial_text = ""
    section = "[/Script/Squad.SquadGameMode]"
    key_prefix = "ReservedSlots"
    items = ["76561198000000001", "76561198000000002"]

    result = _update_ini_array(initial_text, section, key_prefix, items)

    assert section in result
    assert "!ReservedSlots=ClearArray" in result
    assert ".ReservedSlots=76561198000000001" in result
    assert ".ReservedSlots=76561198000000002" in result

def test_update_ini_array_preserves_other_keys_and_sections():
    initial_text = (
        "[General]\n"
        "ServerName=Matefield Server\n"
        "\n"
        "[/Script/Squad.SquadGameMode]\n"
        "MaxPlayers=64\n"
        "!ReservedSlots=ClearArray\n"
        ".ReservedSlots=OLD_STEAM_ID\n"
        "TickRate=30\n"
        "\n"
        "[Admin]\n"
        "Password=secret\n"
    )
    section = "[/Script/Squad.SquadGameMode]"
    key_prefix = "ReservedSlots"
    items = ["NEW_STEAM_ID_1", "NEW_STEAM_ID_2"]

    result = _update_ini_array(initial_text, section, key_prefix, items)

    # Old steam ID should be replaced
    assert "OLD_STEAM_ID" not in result
    assert "!ReservedSlots=ClearArray" in result
    assert ".ReservedSlots=NEW_STEAM_ID_1" in result
    assert ".ReservedSlots=NEW_STEAM_ID_2" in result

    # Other settings must remain intact
    assert "ServerName=Matefield Server" in result
    assert "MaxPlayers=64" in result
    assert "TickRate=30" in result
    assert "Password=secret" in result

def test_update_ini_array_empty_items():
    initial_text = (
        "[/Script/Squad.SquadGameMode]\n"
        "!BannedSlots=ClearArray\n"
        ".BannedSlots=BANNED_ID\n"
    )
    section = "[/Script/Squad.SquadGameMode]"
    key_prefix = "BannedSlots"
    items = []

    result = _update_ini_array(initial_text, section, key_prefix, items)

    assert "!BannedSlots=ClearArray" in result
    assert ".BannedSlots=" not in result
    assert "BANNED_ID" not in result

def test_update_ini_array_consecutive_updates_idempotent():
    initial_text = "[Config]\nKey=Value"
    section = "[Config]"
    key_prefix = "Slots"
    items = ["ID_1", "ID_2"]

    first_update = _update_ini_array(initial_text, section, key_prefix, items)
    second_update = _update_ini_array(first_update, section, key_prefix, items)

    assert first_update == second_update
    assert second_update.count("!Slots=ClearArray") == 1
    assert second_update.count(".Slots=ID_1") == 1
    assert second_update.count(".Slots=ID_2") == 1


def test_update_ini_array_normalizes_crlf():
    initial_text = "[Config]\r\nKey=Value\r\n.Slots=OLD\r\n"
    section = "[Config]"
    key_prefix = "Slots"
    items = ["ID_1", "ID_2"]

    result = _update_ini_array(initial_text, section, key_prefix, items)
    assert "\r" not in result
    assert ".Slots=ID_1" in result
    assert ".Slots=ID_2" in result
    assert ".Slots=OLD" not in result


@pytest.mark.asyncio
async def test_rcon_client_get_bans_from_live_endpoint(mocker):
    from src.connections.apis.rcon import RCONClient
    client = RCONClient("http://fake:7776", "pass")
    
    # Mock _request to simulate /v1/bans returning live bans
    mocker.patch.object(client, "_request", return_value={
        "bans": [{"steamId": "76561198000000001"}, {"steamId": "76561198000000002"}],
        "count": 2
    })
    
    bans = await client.get_bans()
    assert bans == ["76561198000000001", "76561198000000002"]


@pytest.mark.asyncio
async def test_rcon_client_get_bans_fallback_to_config(mocker):
    from src.connections.apis.rcon import RCONClient
    client = RCONClient("http://fake:7776", "pass")
    
    # If /v1/bans raises exception, fallback to config
    async def fake_request(method, endpoint, **kwargs):
        if endpoint == "/v1/bans":
            raise Exception("404 not found")
        return {"text": "[/Script/WDGame.WDGameSession]\n.DefaultBannedPlayerIds=76561198000000099\n", "revision": "rev1"}
        
    mocker.patch.object(client, "_request", side_effect=fake_request)
    bans = await client.get_bans()
    assert bans == ["76561198000000099"]

