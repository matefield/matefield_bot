"""Reserved-slot removal uses Warcon's public API and preserves manual entries."""
from unittest.mock import AsyncMock

import aiohttp
import pytest

from src.connections.apis.warcon import WarconClient, WarconDeliveryError
from wardogs_config import ENVIRONMENT_SETTINGS


@pytest.fixture
def configured_warcon(monkeypatch):
    settings = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    for key, value in {
        "WARCON_URL": "http://warcon.test", "WARCON_ORG_ID": "test-org",
        "WARCON_SERVER_ID": "test-server", "WARCON_API_TOKEN": "wck_test_only",
    }.items():
        monkeypatch.setattr(settings, key, value)
    return WarconClient()


def applied():
    return {"serverId": "test-server", "ok": True, "pending": False, "failed": 0}


def listing(reason="VIP Normal | Discord | ID:#50", **changes):
    return (200, {"ok": True, "entries": [{
        "id": "entry-50", "steamId": "steam-1", "reason": reason, **changes,
    }]})


@pytest.mark.asyncio
@pytest.mark.parametrize("note", [
    "VIP Normal | Discord | ID:#50", "Discord | membership:#50 | VIP Normal",
    "Discord | membership:#50 | type:REGULAR",
])
async def test_remove_own_reserved_entry_confirms_configured_game(configured_warcon, monkeypatch, note):
    requests = AsyncMock(side_effect=[listing(note), (200, {"ok": True, "sync": {"servers": [applied()]}})])
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [39, 50])
    assert result.status == "SUCCESS" and result.entry_id == "entry-50"
    assert [call.args[1:3] for call in requests.await_args_list] == [
        ("GET", "/api/orgs/test-org/lists/reserve/entries"),
        ("DELETE", "/api/orgs/test-org/lists/reserve/entries/steam-1"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("note", [
    "Staff", "VIP Normal", "VIP Normal | Discord | ID:#51",
    "VIP Normal | Discord | ID:#invalid", "VIP Normal | Discord | ID:#١",
    "Discord | membership:#50 | Staff".replace("#50", "#51"),
    "Discord | membership:#0", "Discord | membership:#" + "9" * 5000,
    None,
])
async def test_manual_or_other_membership_slot_is_not_deleted(configured_warcon, monkeypatch, note):
    requests = AsyncMock(return_value=listing(note))
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [50])
    assert result.status == "FAILED"
    assert "no pertenece" in result.error
    assert requests.await_count == 1


@pytest.mark.asyncio
async def test_missing_slot_still_syncs_game_on_retry(configured_warcon, monkeypatch):
    requests = AsyncMock(side_effect=[
        (200, {"ok": True, "entries": [{"steamId": "another-player", "reason": "Staff"}]}),
        (200, {"ok": True, "sync": applied()}),
    ])
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [50])
    assert result.status == "SUCCESS" and result.entry_id is None
    assert requests.await_args.args[1:3] == ("POST", "/api/servers/test-server/lists/sync")


@pytest.mark.asyncio
async def test_delete_known_not_found_rechecks_absence_before_sync(configured_warcon, monkeypatch):
    requests = AsyncMock(side_effect=[
        listing(), (404, {"ok": False, "error": {"code": "not_found"}}),
        (200, {"ok": True, "entries": []}), (200, {"ok": True, "sync": applied()}),
    ])
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [50])
    assert result.status == "SUCCESS"
    assert [call.args[1] for call in requests.await_args_list] == ["GET", "DELETE", "GET", "POST"]


@pytest.mark.asyncio
async def test_delete_not_found_with_new_manual_entry_does_not_sync_or_delete_again(configured_warcon, monkeypatch):
    requests = AsyncMock(side_effect=[listing(), (404, {"error": {"code": "not_found"}}), listing("Staff")])
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [50])
    assert result.status == "FAILED"
    assert requests.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("sync", [
    {**applied(), "pending": True}, {**applied(), "failed": 1},
    {**applied(), "serverId": "other-server"}, {**applied(), "failed": False},
    {**applied(), "error": "RCON unavailable"},
])
async def test_deletion_without_game_confirmation_fails(configured_warcon, monkeypatch, sync):
    requests = AsyncMock(side_effect=[listing(), (200, {"ok": True, "sync": {"servers": [sync]}})])
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [50])
    assert result.status == "FAILED" and result.entry_id == "entry-50"


@pytest.mark.asyncio
@pytest.mark.parametrize("entries", [None, [None], [{}], [{"steamId": None}], [{"steamId": 123}],
    [{"steamId": "other-player", "removedAt": True}], [
    {"steamId": "steam-1"}, {"steamId": "steam-1"},
], [{"steamId": "other-player"}] * 2000])
async def test_ambiguous_or_invalid_roster_does_not_mutate(configured_warcon, monkeypatch, entries):
    requests = AsyncMock(return_value=(200, {"ok": True, "entries": entries}))
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [50])
    assert result.status == "FAILED"
    assert requests.await_count == 1


@pytest.mark.asyncio
async def test_network_failure_after_delete_is_controlled_and_retryable(configured_warcon, monkeypatch):
    requests = AsyncMock(side_effect=[listing(), aiohttp.ClientConnectionError()])
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.remove_reserved_slot("steam-1", [50])
    assert result.status == "FAILED" and result.entry_id == "entry-50"
    assert "Reintentá" in result.error


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        return self.body


class Client:
    def __init__(self, status, body):
        self.response = Response(status, body)

    def request(self, *args, **kwargs):
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["not_found", "route_not_found", None])
async def test_transport_only_accepts_known_delete_not_found(configured_warcon, code):
    client = Client(404, {"ok": False, "error": {"code": code}})
    if code == "not_found":
        status, _ = await configured_warcon._request(client, "DELETE", "/reserve/steam-1")
        assert status == 404
    else:
        with pytest.raises(WarconDeliveryError, match="HTTP 404"):
            await configured_warcon._request(client, "DELETE", "/reserve/steam-1")


@pytest.mark.asyncio
async def test_transport_does_not_treat_get_not_found_as_removed(configured_warcon):
    with pytest.raises(WarconDeliveryError, match="HTTP 404"):
        await configured_warcon._request(Client(404, {"error": {"code": "not_found"}}), "GET", "/reserve")


@pytest.mark.asyncio
async def test_creation_aborted_by_rcon_is_not_a_confirmed_delivery(configured_warcon, monkeypatch):
    requests = AsyncMock(return_value=(201, {
        "ok": True, "entry": {"id": "entry-50"},
        "sync": {"servers": [{**applied(), "error": "RCON unavailable"}]},
    }))
    monkeypatch.setattr(configured_warcon, "_request", requests)
    result = await configured_warcon.upsert_reserved_slot("steam-1", 50, "VIP Normal", None)
    assert result.status == "FAILED"
    assert "RCON unavailable" not in result.error
