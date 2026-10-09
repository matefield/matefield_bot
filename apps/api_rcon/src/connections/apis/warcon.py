"""The public Warcon API owns reserved-slot storage and application to the game."""
from datetime import datetime, timezone
import asyncio
from urllib.parse import urlsplit

import aiohttp
from fastapi import HTTPException
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_schemas.dtos import MembershipWarconDelivery


class WarconDeliveryError(Exception):
    """A safe, user-facing error without remote payloads or credentials."""


class WarconClient:
    NOTE_PREFIX = "Discord | membership:"

    def __init__(self):
        settings = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
        self.base_url = settings.WARCON_URL.strip().rstrip("/")
        self.token = settings.WARCON_API_TOKEN.strip()
        self.org_id = settings.WARCON_ORG_ID.strip()
        self.server_id = settings.WARCON_SERVER_ID.strip()

    def validate_configuration(self) -> None:
        try:
            parsed = urlsplit(self.base_url)
            parsed.port  # Reject malformed or out-of-range ports before saving a membership.
        except ValueError:
            raise HTTPException(status_code=503, detail="Falta configurar la conexión de membresías con Warcon.") from None
        if (
            parsed.scheme not in ("http", "https") or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not self.token or not self.org_id or not self.server_id
        ):
            raise HTTPException(status_code=503, detail="Falta configurar la conexión de membresías con Warcon.")

    async def upsert_reserved_slot(
        self, steam_id: str, membership_id: int, membership_type: str, expires_at: datetime | None
    ) -> MembershipWarconDelivery:
        """Write only this player, preserve manual entries, and confirm the game applied it."""
        self.validate_configuration()
        if expires_at is not None:
            expires_at = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        payload = {
            "steamId": steam_id,
            "reason": f"{self.NOTE_PREFIX}#{membership_id} | type:{membership_type}"[:200],
            "expiresAt": expires_at.astimezone(timezone.utc).isoformat() if expires_at else None,
        }
        entries_path = f"/api/orgs/{self.org_id}/lists/reserve/entries"
        entry_id = None
        try:
            async with asyncio.timeout(25), aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as client:
                status, body = await self._request(client, "POST", entries_path, payload)
                if status == 409 and body.get("error", {}).get("code") == "duplicate":
                    _, listing = await self._request(client, "GET", entries_path)
                    entries = self._rows(listing.get("entries"))
                    entry = next((row for row in entries if row.get("steamId") == steam_id), None)
                    if not entry or not str(entry.get("reason", "")).startswith(self.NOTE_PREFIX):
                        raise WarconDeliveryError("El jugador ya tiene un slot reservado en Warcon que no fue creado por Discord.")
                    entry_id = self._entry_id(entry)
                    await self._request(client, "PATCH", f"{entries_path}/{steam_id}", {
                        "reason": payload["reason"], "expiresAt": payload["expiresAt"],
                    })
                    _, body = await self._request(client, "POST", f"/api/servers/{self.server_id}/lists/sync")
                    result = self._object(body.get("sync"))
                else:
                    entry_id = self._entry_id(self._object(body.get("entry")))
                    sync = self._object(body.get("sync"))
                    servers = self._rows(sync.get("servers"))
                    result = next((row for row in servers if row.get("serverId") == self.server_id), {})
                if result.get("serverId") != self.server_id or not self._applied(result):
                    raise WarconDeliveryError("Warcon guardó el slot, pero no confirmó su aplicación en el servidor de juego.")
            return MembershipWarconDelivery(status="SUCCESS", server_id=self.server_id, entry_id=entry_id)
        except (aiohttp.ClientError, TimeoutError):
            error = "No se pudo confirmar el slot reservado en Warcon. Reintentá esta misma operación."
        except WarconDeliveryError as exc:
            error = str(exc)
        return MembershipWarconDelivery(status="FAILED", server_id=self.server_id, entry_id=entry_id, error=error)

    @staticmethod
    def _object(value) -> dict:
        if not isinstance(value, dict):
            raise WarconDeliveryError("Warcon devolvió una respuesta inválida.")
        return value

    @staticmethod
    def _rows(value) -> list[dict]:
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise WarconDeliveryError("Warcon devolvió una respuesta inválida.")
        return value

    @staticmethod
    def _entry_id(entry: dict) -> str:
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise WarconDeliveryError("Warcon devolvió una respuesta inválida.")
        return entry_id

    @staticmethod
    def _applied(result: dict) -> bool:
        failed = result.get("failed")
        return result.get("ok") is True and result.get("pending") is False and type(failed) is int and failed == 0

    async def _request(self, client, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        async with client.request(method, f"{self.base_url}{path}", json=payload) as response:
            try:
                body = await response.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                raise WarconDeliveryError("Warcon devolvió una respuesta inválida.") from None
            if not isinstance(body, dict):
                raise WarconDeliveryError("Warcon devolvió una respuesta inválida.")
            error = body.get("error")
            if response.status == 409 and method == "POST" and isinstance(error, dict) and error.get("code") == "duplicate":
                return response.status, body
            if response.status >= 400 or body.get("ok") is not True:
                raise WarconDeliveryError(f"Warcon rechazó la operación (HTTP {response.status}).")
            return response.status, body
