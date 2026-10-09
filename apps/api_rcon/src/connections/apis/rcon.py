"""
RCON API client and connection pool manager.

Provides:
- ``RCONClient``: thin async HTTP client for a single game-server RCON API.
- ``RCONManager``: class-level pool that routes requests to the correct
  ``RCONClient`` by (base_url, password) key and falls back to the
  .env-configured server when no DB rows are active.
- ``_update_ini_array`` / ``_is_array_directive``: helpers for patching
  Unreal Engine INI arrays (reserved/banned slots) in-place.
"""
import asyncio
import json
import time
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
from sqlmodel import col, select
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas import v1 as schemas

# Networking and Cache Constants
DEFAULT_RCON_CACHE_TTL = 3.0
DEFAULT_RCON_REQUEST_TIMEOUT = 10.0


def _is_array_directive(line: str, key_prefix: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith((';', '#')):
        return False
    clean = stripped.lstrip('!+.-')
    return clean.startswith(f"{key_prefix}=")


def _update_ini_array(text: str, section: str, key_prefix: str, items: list[str]) -> str:
    """Updates an Unreal Engine INI array under the specified section cleanly without duplicating headers, corrupting formatting, or removing comments."""
    normalized_text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = normalized_text.split('\n')
    new_lines = [line for line in lines if not _is_array_directive(line, key_prefix)]

    insert_idx = -1
    for i, line in enumerate(new_lines):
        if line.strip() == section:
            insert_idx = i
            break

    if insert_idx == -1:
        new_lines.extend(['', section])
        insert_idx = len(new_lines) - 1

    slot_lines = [f'!{key_prefix}=ClearArray']
    for item in items:
        clean_item = str(item).strip().strip('"\'')
        if clean_item:
            slot_lines.append(f'.{key_prefix}={clean_item}')

    result_lines = new_lines[:insert_idx + 1] + slot_lines + new_lines[insert_idx + 1:]
    return '\n'.join(result_lines)


class ReentrantAsyncLock:
    """An asyncio-compatible reentrant lock allowing the same task to acquire multiple times."""
    def __init__(self):
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None
        self._count: int = 0

    async def acquire(self) -> None:
        current_task = asyncio.current_task()
        if self._owner == current_task:
            self._count += 1
            return
        await self._lock.acquire()
        self._owner = current_task
        self._count = 1

    def release(self) -> None:
        current_task = asyncio.current_task()
        if self._owner != current_task:
            raise RuntimeError("Cannot release unowned lock")
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()


class RCONClient:
    def __init__(self, base_url: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.password = password
        self.headers = {
            "Authorization": f"Bearer {self.password}",
            "Content-Type": "application/json"
        }
        self._cache = {}
        self._cache_lock = asyncio.Lock()
        self._config_lock = ReentrantAsyncLock()
        self._cache_ttl = DEFAULT_RCON_CACHE_TTL
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(headers=self.headers, connector=connector)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get_cached(self, key: str, fetcher_coro) -> Any:
        async with self._cache_lock:
            now = time.time()
            if key in self._cache:
                timestamp, data = self._cache[key]
                if now - timestamp < self._cache_ttl:
                    return data
            # Fetch new data
            data = await fetcher_coro()
            # Update cache timestamp AFTER fetch succeeds
            self._cache[key] = (time.time(), data)
            return data

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.base_url}{endpoint}"
        session = await self._get_session()
        timeout = kwargs.pop("timeout", aiohttp.ClientTimeout(total=DEFAULT_RCON_REQUEST_TIMEOUT))
        async with session.request(method, url, timeout=timeout, **kwargs) as response:
            response.raise_for_status()
            if "application/json" in response.headers.get("Content-Type", ""):
                return await response.json()
            return await response.text()

    async def get_status(self) -> schemas.Status:
        async def fetch():
            data = await self._request("GET", "/v1/status")
            return schemas.Status.model_validate(data)
        return await self._get_cached("status", fetch)

    async def get_players(self) -> schemas.Players1:
        async def fetch():
            data = await self._request("GET", "/v1/players")
            return schemas.Players1.model_validate(data)
        return await self._get_cached("players", fetch)

    async def get_audit_logs(self, limit: int = 50) -> schemas.Audit:
        data = await self._request("GET", f"/v1/audit?limit={limit}")
        return schemas.Audit.model_validate(data)

    async def get_reserved_slots(self) -> schemas.ReservedSlots:
        data = await self._request("GET", "/v1/reserved-slots")
        return schemas.ReservedSlots.model_validate(data)

    async def sync_reserved_slots(self, steam_ids: list[str]) -> None:
        async with self._config_lock:
            for attempt in range(3):
                try:
                    config = await self.get_config()
                    text = config.text or ""
                    revision = config.revision or ""
                    new_text = _update_ini_array(text, '[/Script/WDGame.WDGameSession]', 'DefaultReservedPlayerIds', steam_ids)
                    await self.update_config(revision, new_text)
                    return
                except aiohttp.ClientResponseError as e:
                    if e.status == 412 and attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    raise

    async def get_bans(self) -> list[str]:
        # Try live route /v1/bans first (build CL-499480 & CL-501228 serve this)
        try:
            data = await self._request("GET", "/v1/bans")
            if isinstance(data, dict) and "bans" in data:
                return [b["steamId"] for b in data["bans"] if isinstance(b, dict) and b.get("steamId")]
        except Exception:
            pass

        # Fallback to parsing ServerSettings.ini from /v1/config
        config = await self.get_config()
        text = config.text or ""
        lines = text.split('\n')
        bans = []
        for line in lines:
            line = line.strip()
            if line.startswith('.DefaultBannedPlayerIds=') or line.startswith('+DefaultBannedPlayerIds='):
                val = line.split('=', 1)[1].strip().strip('"\'')
                if val:
                    bans.append(val)
        return bans

    async def sync_banned_slots(self, steam_ids: list[str]) -> None:
        async with self._config_lock:
            for attempt in range(3):
                try:
                    config = await self.get_config()
                    text = config.text or ""
                    revision = config.revision or ""
                    new_text = _update_ini_array(text, '[/Script/WDGame.WDGameSession]', 'DefaultBannedPlayerIds', steam_ids)
                    await self.update_config(revision, new_text)
                    return
                except aiohttp.ClientResponseError as e:
                    if e.status == 412 and attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    raise

    async def broadcast(self, message: str) -> None:
        await self._request("POST", "/v1/broadcast", json={"message": message})

    async def send_player_message(self, steam_id: str, message: str) -> None:
        safe_id = quote(str(steam_id))
        await self._request("POST", f"/v1/players/{safe_id}/message", json={"message": message})

    async def get_config(self) -> schemas.Config1:
        data = await self._request("GET", "/v1/config")
        if isinstance(data, str):
            data = json.loads(data)
        return schemas.Config1.model_validate(data)

    async def update_config(self, revision: str, new_text: str) -> schemas.ConfigResult:
        async with self._config_lock:
            headers = {
                "If-Match": f'"{revision}"',
                "Content-Type": "text/plain"
            }
            data = await self._request("PUT", "/v1/config?force=true&fullApply=true", headers=headers, data=new_text)
            if isinstance(data, str):
                data = json.loads(data)
            return schemas.ConfigResult.model_validate(data)
        
    async def kick_player(self, steam_id: str, reason: str) -> None:
        safe_id = quote(str(steam_id))
        payload = {"reason": reason}
        await self._request("POST", f"/v1/players/{safe_id}/kick", json=payload)

    async def ban_player(self, steam_id: str, reason: str) -> None:
        payload = {"steamId": str(steam_id), "reason": reason}
        await self._request("POST", "/v1/bans", json=payload)

    async def unban_player(self, steam_id: str) -> None:
        safe_id = quote(str(steam_id))
        try:
            await self._request("DELETE", f"/v1/bans/{safe_id}")
        except Exception:
            # Server returns 404 if player is already unbanned
            pass

    async def switch_faction(self, steam_id: str, faction: str) -> None:
        safe_id = quote(str(steam_id))
        payload = {"faction": faction}
        await self._request("POST", f"/v1/players/{safe_id}/faction", json=payload)

# Instance to be imported by legacy callers
rcon_client = RCONClient(
    base_url=ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.RCON_URL,
    password=ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.RCON_PASSWORD
)


class RCONManager:
    """Manages connection pooling and routing for multiple RCON servers."""
    _clients: dict[tuple[str, str], RCONClient] = {}

    @classmethod
    def _ensure_default_registered(cls) -> None:
        default_key = (
            ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.RCON_URL.rstrip("/"),
            ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.RCON_PASSWORD
        )
        if default_key not in cls._clients:
            cls._clients[default_key] = rcon_client

    @classmethod
    def get_client(cls, base_url: str, password: str) -> RCONClient:
        cls._ensure_default_registered()
        key = (base_url.rstrip("/"), password)
        if key not in cls._clients:
            cls._clients[key] = RCONClient(base_url=base_url, password=password)
        return cls._clients[key]

    @classmethod
    def register_client(cls, base_url: str, password: str, client: RCONClient) -> None:
        """Explicitly register or mock a client instance for testing or custom routing."""
        key = (base_url.rstrip("/"), password)
        cls._clients[key] = client

    @classmethod
    def reset_pool(cls) -> None:
        """Resets the connection pool (useful between test runs)."""
        cls._clients.clear()
        cls._ensure_default_registered()

    @classmethod
    async def close_all(cls) -> None:
        """Closes all client sessions in the pool."""
        for client in list(cls._clients.values()):
            await client.close()
        cls._clients.clear()

    @classmethod
    def get_client_for_server(cls, server: Any) -> RCONClient:
        return cls.get_client(server.base_url, server.password)

    @classmethod
    def _get_fallback_server(cls) -> Any:
        """Constructs a fallback RconServer instance from .env configurations."""
        from src.connections.databases.db import RconServer
        clean_url = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.RCON_URL.rstrip("/")
        parsed = urlparse(clean_url if "://" in clean_url else f"http://{clean_url}")
        scheme = parsed.scheme or "http"
        ip = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if scheme == "https" else 80)
        return RconServer(
            id=0,
            name="Default (.env)",
            ip=ip,
            port=port,
            password=ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.RCON_PASSWORD,
            scheme=scheme,
            is_active=True,
            is_default=True
        )

    @classmethod
    async def get_all_active_servers(cls, session: Any) -> list[tuple[Any, RCONClient]]:
        from src.connections.databases.db import RconServer
        stmt = select(RconServer).where(RconServer.is_active == True).order_by(col(RconServer.is_default).desc(), col(RconServer.id))
        servers = (await session.exec(stmt)).all()
        if not servers:
            fallback = cls._get_fallback_server()
            return [(fallback, cls.get_client(fallback.base_url, fallback.password))]
        return [(s, cls.get_client_for_server(s)) for s in servers]

    @classmethod
    async def get_default_server(cls, session: Any) -> tuple[Any, RCONClient]:
        from src.connections.databases.db import RconServer
        stmt = select(RconServer).where(RconServer.is_active == True, RconServer.is_default == True)
        default_server = (await session.exec(stmt)).first()
        if not default_server:
            stmt_any = select(RconServer).where(RconServer.is_active == True).order_by(col(RconServer.id))
            default_server = (await session.exec(stmt_any)).first()

        if default_server:
            return default_server, cls.get_client_for_server(default_server)

        fallback = cls._get_fallback_server()
        return fallback, cls.get_client(fallback.base_url, fallback.password)


