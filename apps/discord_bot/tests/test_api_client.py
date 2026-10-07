from wardogs_schemas import v1 as schemas
import pytest
import aiohttp
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

client_path = Path(__file__).resolve().parent.parent / "src" / "api_client.py"
spec = importlib.util.spec_from_file_location("discord_bot_api_client", client_path)
assert spec is not None and spec.loader is not None
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)
APIClient = client_module.APIClient


@pytest.mark.asyncio
async def test_api_client_session_pooling():
    client = APIClient(base_url="http://127.0.0.1:8000", api_key="secret-key")
    assert client._session is None

    # First session creation
    session1 = await client._get_session()
    assert isinstance(session1, aiohttp.ClientSession)
    assert not session1.closed

    # Second call must reuse the exact same session (pooling)
    session2 = await client._get_session()
    assert session2 is session1

    # Clean close
    await client.close()
    assert session1.closed

    # Getting session again recreates a fresh session
    session3 = await client._get_session()
    assert session3 is not session1
    assert not session3.closed

    await client.close()


@pytest.mark.asyncio
async def test_api_client_headers():
    client = APIClient(base_url="http://api.matefield.com/", api_key="test-api-key")
    assert client.base_url == "http://api.matefield.com"
    assert client.headers["X-API-Key"] == "test-api-key"
    assert client.headers["Content-Type"] == "application/json"
    await client.close()


@pytest.mark.asyncio
async def test_api_client_request_delegation():
    client = APIClient(base_url="http://127.0.0.1:8000", api_key="secret-key")

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.json = AsyncMock(return_value={"ok": True, "total": 5})
    mock_response.raise_for_status = MagicMock()

    mock_request_ctx = AsyncMock()
    mock_request_ctx.__aenter__.return_value = mock_response

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_request_ctx) as mock_req:
        result = await client._request("GET", "/api/v1/test")
        mock_req.assert_called_once()
        assert mock_req.call_args[0] == ("GET", "http://127.0.0.1:8000/api/v1/test")
        assert "timeout" in mock_req.call_args[1]

    await client.close()


@pytest.mark.asyncio
async def test_api_client_download_file_bytes():
    client = APIClient(base_url="http://127.0.0.1:8000", api_key="secret-key")

    mock_response = AsyncMock()
    mock_response.read = AsyncMock(return_value=b"col1,col2\nval1,val2")
    mock_response.raise_for_status = MagicMock()

    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_response

    with patch.object(aiohttp.ClientSession, "get", return_value=mock_get_ctx) as mock_get:
        data = await client.download_file_bytes("/api/v1/download/test.csv")
        assert data == b"col1,col2\nval1,val2"
        mock_get.assert_called_once_with("http://127.0.0.1:8000/api/v1/download/test.csv")

    await client.close()


@pytest.mark.asyncio
async def test_api_client_rewards_methods():
    client = APIClient(base_url="http://127.0.0.1:8000", api_key="secret-key")

    mock_req = AsyncMock(return_value=[{"id": 1, "code": "VIP", "name": "VIP", "description": "desc", "cost_points": 100, "is_active": True, "reward_type": "discord_role", "reward_value": "123", "delivery_type": "automatic"}])
    client._request = mock_req

    # 1. get_rewards_catalog
    await client.get_rewards_catalog(only_active=True)
    mock_req.assert_called_with("GET", "/api/v1/rewards/catalog?only_active=True")

    # 2. get_player_rewards_balance
    mock_req.return_value = {"steam_id": "123456789", "reward_points": 100, "total_seeding_minutes": 200}
    await client.get_player_rewards_balance("123456789")
    mock_req.assert_called_with("GET", "/api/v1/rewards/balance/123456789")

    # 3. claim_reward
    mock_req.return_value = {"ok": True, "claim_code": "XX", "reward_name": "VIP", "reward_code": "VIP", "cost_points": 100, "remaining_points": 0, "status": "PENDING", "delivery": {"delivery_type": "AUTOMATIC"}}
    await client.claim_reward("123456789", "VIP_MONTH")
    assert mock_req.call_args[0] == ("POST", "/api/v1/rewards/claim")
    assert mock_req.call_args[1]["json"]["reward_code"] == "VIP_MONTH"

    # 4. verify_reward_claim
    mock_req.return_value = {}
    await client.verify_reward_claim("MF-1111-2222")
    mock_req.assert_called_with("GET", "/api/v1/rewards/admin/verify/MF-1111-2222")

    # 5. deliver_reward_claim
    mock_req.return_value = {}
    await client.deliver_reward_claim("MF-1111-2222", delivered_by="Admin#0001", notes="Key given")
    assert mock_req.call_args[0] == ("POST", "/api/v1/rewards/admin/deliver/MF-1111-2222")

    # 6. refund_reward_claim
    await client.refund_reward_claim("MF-1111-2222", refunded_by="Admin#0001", reason="Out of stock")
    assert mock_req.call_args[0] == ("POST", "/api/v1/rewards/admin/refund/MF-1111-2222")

    # 7. give_reward_points
    await client.give_reward_points("123456789", points=50, reason="Event prize")
    assert mock_req.call_args[0] == ("POST", "/api/v1/rewards/admin/give_points")
    assert mock_req.call_args[1]["json"]["points"] == 50

    await client.close()

