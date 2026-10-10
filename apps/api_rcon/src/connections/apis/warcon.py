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
    NOTE_PREFIX = "Discord | membership:"  # Existing entries remain owned by Discord.
    NOTE_MARKER = " | Discord | ID:#"

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
        self, steam_id: str, membership_id: int, membership_type_name: str, expires_at: datetime | None
    ) -> MembershipWarconDelivery:
        """Write only this player, preserve manual entries, and confirm the game applied it."""
        self.validate_configuration()
        if expires_at is not None:
            expires_at = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        note_suffix = f"{self.NOTE_MARKER}{membership_id}"
        payload = {
            "steamId": steam_id,
            "reason": f"{membership_type_name[:200 - len(note_suffix)]}{note_suffix}",
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
                    if not entry or not self._is_discord_note(str(entry.get("reason", ""))):
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

    async def remove_reserved_slot(
        self, steam_id: str, membership_ids: list[int]
    ) -> MembershipWarconDelivery:
        """Remove this player's Discord entry and require confirmation from the game.

        Historical membership IDs are supplied by our API, so an entry associated
        with a different player or a manually managed slot is rejected before deletion.
        A missing entry still requires a sync: a prior DELETE may have succeeded
        while its game delivery or response failed.
        """
        self.validate_configuration()
        entries_path = f"/api/orgs/{self.org_id}/lists/reserve/entries"
        entry_id = None
        try:
            async with asyncio.timeout(25), aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as client:
                entry = await self._reserved_entry(client, entries_path, steam_id)
                if entry is not None:
                    membership_id = self._discord_membership_id(entry.get("reason"))
                    if membership_id is None or membership_id not in membership_ids:
                        raise WarconDeliveryError(
                            "El slot reservado de Warcon no pertenece a una membresía de este jugador creada desde Discord."
                        )
                    entry_id = self._entry_id(entry)
                    status, body = await self._request(client, "DELETE", f"{entries_path}/{steam_id}")
                    if status == 404:
                        # A concurrent removal is safe only if the entry is now absent.
                        if await self._reserved_entry(client, entries_path, steam_id) is not None:
                            raise WarconDeliveryError("Warcon no confirmó la eliminación del slot reservado.")
                        result = None
                    else:
                        servers = self._rows(self._object(body.get("sync")).get("servers"))
                        result = next((row for row in servers if row.get("serverId") == self.server_id), {})
                else:
                    result = None
                if result is None:
                    _, body = await self._request(client, "POST", f"/api/servers/{self.server_id}/lists/sync")
                    result = self._object(body.get("sync"))
                if result.get("serverId") != self.server_id or not self._applied(result):
                    raise WarconDeliveryError(
                        "Warcon no confirmó la retirada del slot reservado en el servidor de juego. Reintentá la baja."
                    )
            return MembershipWarconDelivery(status="SUCCESS", server_id=self.server_id, entry_id=entry_id)
        except (aiohttp.ClientError, TimeoutError):
            error = "No se pudo confirmar la retirada del slot reservado en Warcon. Reintentá la baja."
        except WarconDeliveryError as exc:
            error = str(exc)
        return MembershipWarconDelivery(status="FAILED", server_id=self.server_id, entry_id=entry_id, error=error)

    async def _reserved_entry(self, client, entries_path: str, steam_id: str) -> dict | None:
        _, listing = await self._request(client, "GET", entries_path)
        entries = self._rows(listing.get("entries"))
        if any(
            not isinstance(row.get("steamId"), str) or not row["steamId"].strip()
            or (row.get("removedAt") is not None and not isinstance(row["removedAt"], str))
            for row in entries
        ):
            raise WarconDeliveryError("Warcon devolvió una respuesta inválida.")
        matches = [row for row in entries if row.get("steamId") == steam_id and not row.get("removedAt")]
        if len(matches) > 1 or (not matches and len(entries) >= 2000):
            # Warcon's public roster is capped at 2000 entries; absence is ambiguous at that limit.
            raise WarconDeliveryError("Warcon no permitió identificar de forma segura el slot reservado del jugador.")
        return matches[0] if matches else None

    @classmethod
    def _discord_membership_id(cls, reason) -> int | None:
        if not isinstance(reason, str):
            return None
        if reason.startswith(cls.NOTE_PREFIX):
            identifier = reason[len(cls.NOTE_PREFIX):].split(" | ", 1)[0]
            identifier = identifier[1:] if identifier.startswith("#") else ""
        else:
            name, marker, identifier = reason.rpartition(cls.NOTE_MARKER)
            if not name.strip() or not marker:
                return None
        if not identifier.isascii() or not identifier.isdecimal() or len(identifier) > 10:
            return None
        value = int(identifier)
        return value if 0 < value <= 2147483647 else None

    @classmethod
    def _is_discord_note(cls, reason: str) -> bool:
        name, marker, membership_id = reason.rpartition(cls.NOTE_MARKER)
        return reason.startswith(cls.NOTE_PREFIX) or bool(
            name.strip() and marker and membership_id.isascii() and membership_id.isdecimal()
        )

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
        return (
            result.get("ok") is True and result.get("pending") is False
            and type(failed) is int and failed == 0 and result.get("error", "") == ""
        )

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
            if response.status == 404 and method == "DELETE" and isinstance(error, dict) and error.get("code") == "not_found":
                return response.status, body
            if response.status >= 400 or body.get("ok") is not True:
                raise WarconDeliveryError(f"Warcon rechazó la operación (HTTP {response.status}).")
            return response.status, body
