import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.apis.rcon import RCONClient, RCONManager
from src.connections.databases.db import RconServer
from wardogs_schemas import v1 as schemas


@pytest.mark.asyncio
async def test_rcon_servers_crud_flow(client: AsyncClient, session: AsyncSession, mocker):
    dummy_status = schemas.Status(
        serverName="Servidor de Prueba Alpha",
        map="Desert_Valley",
        players=schemas.Players(current=12, max=64),
        matchSeconds=300
    )
    mocker.patch.object(RCONClient, "get_status", return_value=dummy_status)

    # 1. Initially empty
    list_resp = await client.get("/api/v1/rcon-servers?check_health=false")
    assert list_resp.status_code == 200
    assert list_resp.json() == []

    # 2. Create server without name (should auto-probe status)
    create_resp = await client.post("/api/v1/rcon-servers", json={
        "ip": "10.0.0.1",
        "port": 7777,
        "password": "pass",
        "scheme": "http",
        "is_active": True,
        "is_default": True
    })
    assert create_resp.status_code == 200
    created = create_resp.json()["server"]
    server_id = created["id"]
    assert created["name"] == "Servidor de Prueba Alpha"
    assert created["is_default"] is True

    # 3. Get server by ID
    get_resp = await client.get(f"/api/v1/rcon-servers/{server_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Servidor de Prueba Alpha"

    # 4. Update server
    put_resp = await client.put(f"/api/v1/rcon-servers/{server_id}", json={
        "name": "Servidor Modificado",
        "port": 8888
    })
    assert put_resp.status_code == 200
    updated = put_resp.json()["server"]
    assert updated["name"] == "Servidor Modificado"
    assert updated["port"] == 8888

    # 5. Test server endpoint
    test_resp = await client.post(f"/api/v1/rcon-servers/{server_id}/test")
    assert test_resp.status_code == 200
    test_data = test_resp.json()
    assert test_data["is_online"] is True
    assert test_data["current_map"] == "Desert_Valley"
    assert test_data["player_count"] == 12

    # 6. Delete server
    del_resp = await client.delete(f"/api/v1/rcon-servers/{server_id}")
    assert del_resp.status_code == 200

    # 7. Confirm 404 after deletion
    del_get_resp = await client.get(f"/api/v1/rcon-servers/{server_id}")
    assert del_get_resp.status_code == 404


@pytest.mark.asyncio
async def test_rcon_client_get_bans_empty_list_does_not_call_get_config(mocker):
    """Verifies that an empty ban list from /v1/bans returns immediately without unnecessary config fetch."""
    rcon = RCONClient(base_url="http://127.0.0.1:8000", password="test")
    mock_req = mocker.patch.object(rcon, "_request", return_value={"bans": []})
    mock_get_config = mocker.patch.object(rcon, "get_config")

    bans = await rcon.get_bans()
    assert bans == []
    mock_req.assert_called_once_with("GET", "/v1/bans")
    mock_get_config.assert_not_called()


@pytest.mark.asyncio
async def test_rcon_manager_fallback_server_parses_url_safely():
    """Verifies that RCONManager._get_fallback_server correctly constructs RconServer from environment URL."""
    fallback = RCONManager._get_fallback_server()
    assert fallback is not None
    assert fallback.id == 0
    assert fallback.name == "Default (.env)"
    assert fallback.scheme in ("http", "https")
    assert fallback.ip is not None
    assert fallback.port > 0
    assert fallback.is_active is True
    assert fallback.is_default is True


@pytest.mark.asyncio
async def test_delete_rcon_server_detaches_memberships_and_reassigns_default(session: AsyncSession):
    from src.connections.databases.db import Membership, MembershipType, Player
    from src.modules.v1.services.rcon_servers_service import RconServersService

    # 1. Create two servers
    s1 = RconServer(name="Server 1", ip="127.0.0.1", port=1111, password="p1", is_default=True, is_active=True)
    s2 = RconServer(name="Server 2", ip="127.0.0.1", port=2222, password="p2", is_default=False, is_active=True)
    session.add(s1)
    session.add(s2)
    await session.commit()
    await session.refresh(s1)
    await session.refresh(s2)

    # 2. Attach a player, membership, and membership type to Server 1
    player = Player(steam_id="76561198000000099")
    session.add(player)
    await session.commit()

    m = Membership(steam_id="76561198000000099", membership_type="VIP_PRO", server_id=s1.id, is_active=True)
    mt = MembershipType(code="VIP_SERVER1", name="VIP Server 1", server_id=s1.id)
    session.add(m)
    session.add(mt)
    await session.commit()
    await session.refresh(m)
    await session.refresh(mt)
    assert m.server_id == s1.id
    assert mt.server_id == s1.id

    # 3. Delete Server 1
    res = await RconServersService.delete_server(s1.id, session)
    assert res["ok"] is True

    # 4. Check memberships & membership_types detached without FK errors
    await session.refresh(m)
    await session.refresh(mt)
    assert m.server_id is None
    assert mt.server_id is None

    # 5. Check Server 2 was promoted to default
    await session.refresh(s2)
    assert s2.is_default is True

