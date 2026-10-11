import asyncio
import logging
from typing import Any

import aiohttp
from wardogs_schemas import dtos as schemas
from wardogs_schemas import v1 as rcon_schemas

logger = logging.getLogger(__name__)

class APIClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    DEFAULT_API_TIMEOUT = 15.0

    async def _request(self, method: str, endpoint: str, retries: int = 3, **kwargs) -> Any:
        url = f"{self.base_url}{endpoint}"
        session = await self._get_session()
        timeout = kwargs.pop("timeout", aiohttp.ClientTimeout(total=self.DEFAULT_API_TIMEOUT))
        
        for attempt in range(retries):
            try:
                async with session.request(method, url, timeout=timeout, **kwargs) as response:
                    if response.status >= 400:
                        detail = None
                        try:
                            data = await response.json()
                            if isinstance(data, dict) and "detail" in data:
                                detail = data["detail"]
                        except Exception:
                            pass
                        if detail is None:
                            detail = await response.text()
                        raise Exception(f"HTTP {response.status}: {detail}")
                    response.raise_for_status()
                    if "application/json" in response.headers.get("Content-Type", ""):
                        return await response.json()
                    return await response.text()
            except aiohttp.ClientError as e:
                if attempt == retries - 1:
                    logger.error(f"API request failed after {retries} attempts: {method} {endpoint} - {e}")
                    raise Exception(f"Error de conexión con la API: {e}") from e
                
                wait_time = 2 ** attempt
                logger.warning(f"Connection error to {endpoint}: {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

    # RCON wrapped endpoints
    async def get_status(self) -> rcon_schemas.Status:
        data = await self._request("GET", "/api/v1/status")
        return rcon_schemas.Status.model_validate(data)

    async def get_players(self) -> rcon_schemas.Players1:
        data = await self._request("GET", "/api/v1/players")
        return rcon_schemas.Players1.model_validate(data)


    async def get_audit_logs(self, limit: int = 50) -> rcon_schemas.Audit:
        data = await self._request("GET", f"/api/v1/audit?limit={limit}")
        return rcon_schemas.Audit.model_validate(data)

    async def get_reserved_slots(self) -> rcon_schemas.ReservedSlots:
        data = await self._request("GET", "/api/v1/reserved-slots")
        return rcon_schemas.ReservedSlots.model_validate(data)

    async def add_reserved_slot(self, steam_id: str) -> None:
        await self._request("POST", "/api/v1/reserved-slots", json={"steamId": steam_id})

    async def remove_reserved_slot(self, steam_id: str) -> None:
        await self._request("DELETE", f"/api/v1/reserved-slots/{steam_id}")

    async def broadcast(self, message: str) -> None:
        await self._request("POST", "/api/v1/broadcast", json={"message": message})

    async def send_player_message(self, steam_id: str, message: str) -> None:
        await self._request("POST", f"/api/v1/players/{steam_id}/message", json={"message": message})

    async def get_config(self) -> rcon_schemas.Config1:
        data = await self._request("GET", "/api/v1/config")
        return rcon_schemas.Config1.model_validate(data)

    async def update_config(self, revision: str, new_text: str) -> rcon_schemas.ConfigResult:
        data = await self._request("PUT", "/api/v1/config", json={"revision": revision, "new_text": new_text})
        return rcon_schemas.ConfigResult.model_validate(data)

    # Database endpoints
    async def link_account(self, discord_id: str, steam_id: str) -> None:
        req = schemas.LinkAccountRequest(discord_id=discord_id, steam_id=steam_id)
        await self._request("POST", "/api/v1/db/players/link", json=req.model_dump())

    async def unlink_account(self, discord_id: str) -> None:
        req = schemas.UnlinkAccountRequest(discord_id=discord_id)
        await self._request("POST", "/api/v1/db/players/unlink", json=req.model_dump())

    async def get_player_by_discord(self, discord_id: str) -> schemas.PlayerResponse | None:
        try:
            res = await self._request("GET", f"/api/v1/db/players/discord/{discord_id}")
            if isinstance(res, dict) and "discord_id" not in res:
                res["discord_id"] = discord_id
            return schemas.PlayerResponse(**res)
        except Exception as e:
            if "HTTP 404" in str(e):
                return None
            raise

    async def get_player_by_steam(self, steam_id: str) -> schemas.PlayerResponse | None:
        try:
            res = await self._request("GET", f"/api/v1/db/players/steam/{steam_id}")
            if isinstance(res, dict) and "steam_id" not in res:
                res["steam_id"] = steam_id
            return schemas.PlayerResponse(**res)
        except Exception as e:
            if "HTTP 404" in str(e):
                return None
            raise

    async def set_welcome_message(self, steam_id: str, message: str) -> None:
        await self._request("POST", f"/api/v1/db/players/steam/{steam_id}/welcome-message", json={"message": message})

    async def add_membership(self, steam_id: str, membership_type: str, days: int | None = None, special_role: str | None = None, special_role_id: int | None = None, role_granted_id: int | None = None, is_booster: bool = False, server_id: int | None = None) -> None:
        req = schemas.AddMembershipRequest(
            steam_id=steam_id,
            membership_type=membership_type,
            days=days,
            special_role=special_role,
            special_role_id=special_role_id,
            role_granted_id=role_granted_id,
            is_booster=is_booster,
            server_id=server_id
        )
        await self._request("POST", "/api/v1/db/players/membership", json=req.model_dump(exclude_none=False))

    async def edit_membership(self, membership_id: int, days: int | None = None, add_days: int | None = None, membership_type: str | None = None, is_active: bool | None = None, is_booster: bool | None = None, server_id: int | None = None) -> None:
        kwargs: dict[str, Any] = {
            "days": days,
            "add_days": add_days,
            "membership_type": membership_type,
            "is_active": is_active,
            "is_booster": is_booster,
        }
        if server_id is not None:
            kwargs["server_id"] = server_id
        req = schemas.EditMembershipRequest(**kwargs)
        await self._request("PUT", f"/api/v1/db/memberships/{membership_id}", json=req.model_dump(exclude_unset=True))

    async def compensate_memberships(self, days: int) -> dict[str, Any]:
        req = schemas.CompensateRequest(days=days)
        return await self._request("POST", "/api/v1/db/memberships/compensate", json=req.model_dump())

    async def delete_membership(self, membership_id: int) -> None:
        await self._request("DELETE", f"/api/v1/db/memberships/{membership_id}")

    async def export_memberships(self) -> dict[str, Any]:
        data = await self._request("POST", "/api/v1/db/memberships/export")
        return schemas.ExportMembershipsResponse.model_validate(data).model_dump()

    async def download_file_bytes(self, endpoint: str) -> bytes:
        url = f"{self.base_url}{endpoint}"
        session = await self._get_session()
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()

    async def remove_special_role(self, steam_id: str, role_id: str) -> None:
        await self._request("DELETE", f"/api/v1/db/players/{steam_id}/roles/{role_id}")

    async def edit_player(self, steam_id: str, discord_id: str | None = None, custom_welcome_message: str | None = None, observations: str | None = None) -> None:
        req = schemas.EditPlayerRequest(
            discord_id=discord_id,
            custom_welcome_message=custom_welcome_message,
            observations=observations
        )
        await self._request("PUT", f"/api/v1/db/players/{steam_id}", json=req.model_dump(exclude_unset=True))

    async def export_table_csv(self, table_name: str) -> str:
        # Returns raw CSV text
        return await self._request("GET", f"/api/v1/db/export/{table_name}")

    async def sync_memberships(self) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/db/sync_memberships")

    async def get_leaderboard(self, metric: str = "kills", limit: int = 15) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/db/leaderboard?metric={metric}&limit={limit}")

    async def get_bot_config(self, key: str) -> str | None:
        try:
            res = await self._request("GET", f"/api/v1/bot/config/{key}")
            return res.get("value")
        except Exception as e:
            if "HTTP 404" in str(e):
                return None
            raise

    async def get_bot_configs(self) -> dict[str, str]:
        res = await self._request("GET", "/api/v1/bot/configs")
        return res.get("configs", {})

    async def set_bot_config(self, key: str, value: str) -> None:
        payload = schemas.SetBotConfigRequest(key=key, value=value).model_dump()
        await self._request("PUT", "/api/v1/bot/config", json=payload)
        
    async def get_quotas(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/db/quotas")
        
    async def update_quota(self, membership_type: str, max_quota: int | None) -> dict[str, Any]:
        payload = schemas.QuotaUpdateRequest(max_quota=max_quota).model_dump()
        return await self._request("PUT", f"/api/v1/db/quotas/{membership_type}", json=payload)

    async def delete_bot_config(self, key: str) -> None:
        await self._request("DELETE", f"/api/v1/bot/config/{key}")

    async def get_paginated_players(self, page: int = 1, limit: int = 10, linked: str = "all") -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/db/players?page={page}&limit={limit}&linked={linked}")

    async def get_paginated_matches(self, page: int = 1, limit: int = 10) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/db/matches?page={page}&limit={limit}")
        
    async def get_paginated_memberships(self, page: int = 1, limit: int = 10, discord_id: str | None = None) -> dict[str, Any]:
        url = f"/api/v1/db/memberships?page={page}&limit={limit}"
        if discord_id:
            url += f"&discord_id={discord_id}"
        return await self._request("GET", url)

    async def get_steam_player(self, steam_id: str) -> dict[str, Any] | None:
        try:
            return await self._request("GET", f"/api/v1/steam/player/{steam_id}")
        except Exception:
            return None
            
    async def get_steam_players_batch(self, steam_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not steam_ids:
            return {}
        try:
            return await self._request("GET", f"/api/v1/steam/players?steam_ids={','.join(steam_ids)}")
        except Exception:
            return {}
            
    async def get_player_historical_stats(self, steam_id: str) -> dict[str, Any] | None:
        try:
            return await self._request("GET", f"/api/v1/db/players/steam/{steam_id}/stats")
        except Exception:
            return None

    async def kick_player(self, steam_id: str, reason: str) -> None:
        payload = rcon_schemas.ReasonRequest(reason=reason).model_dump(exclude_none=True)
        await self._request("POST", f"/api/v1/players/{steam_id}/kick", json=payload)

    async def ban_player(self, steam_id: str, reason: str, duration_days: int = 0, solo_discord: bool = False) -> None:
        payload = rcon_schemas.ReasonRequest(reason=reason, duration_days=duration_days, solo_discord=solo_discord).model_dump(exclude_none=True)
        await self._request("POST", f"/api/v1/players/{steam_id}/ban", json=payload)
        
    async def unban_player(self, steam_id: str) -> None:
        await self._request("POST", f"/api/v1/players/{steam_id}/unban")

    async def sync_bans(self) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/db/sync_bans")

    async def switch_faction(self, steam_id: str, faction: str) -> None:
        payload = rcon_schemas.FactionRequest(faction=faction).model_dump()
        await self._request("POST", f"/api/v1/players/{steam_id}/faction", json=payload)

    async def get_rcon_sync_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/db/rcon_sync_status")

    async def add_special_role(self, steam_id: str, role_id: str) -> None:
        await self._request("POST", f"/api/v1/db/players/{steam_id}/roles/{role_id}")

    async def get_latest_match(self) -> dict[str, Any] | None:
        try:
            return await self._request("GET", "/api/v1/db/matches/latest")
        except Exception:
            return None

    async def get_all_roles(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        import time
        now = time.time()
        if not force_refresh and hasattr(self, "_roles_cache") and self._roles_cache and (now - self._roles_cache[0] < 15):
            return self._roles_cache[1]
        try:
            roles = await self._request("GET", "/api/v1/db/roles")
            self._roles_cache = (now, roles)
            return roles
        except Exception:
            return getattr(self, "_roles_cache", (0, []))[1] if getattr(self, "_roles_cache", None) else []

    async def get_players_by_role(self, role_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/api/v1/db/roles/{role_id}/players")

    async def register_role(self, code: str, name: str, role_type: str, discord_role_id: str) -> None:
        self._roles_cache = None
        payload = schemas.RoleRegisterRequest(
            code=code,
            name=name,
            role_type=role_type,
            discord_role_id=discord_role_id
        ).model_dump()
        await self._request("POST", "/api/v1/db/roles", json=payload)

    async def give_player_role(self, steam_id: str, role_id: str) -> None:
        await self.add_special_role(steam_id, role_id)

    async def remove_player_role(self, steam_id: str, role_id: str) -> None:
        await self.remove_special_role(steam_id, role_id)

    # RCON Server management endpoints
    async def get_rcon_servers(self) -> list[schemas.RconServerItem]:
        res = await self._request("GET", "/api/v1/rcon-servers")
        return [schemas.RconServerItem(**x) for x in res]

    async def create_rcon_server(
        self,
        ip: str,
        port: int,
        password: str,
        name: str | None = None,
        scheme: str = "http",
        is_active: bool = True,
        is_default: bool = False
    ) -> schemas.RconServerActionResponse:
        req = schemas.CreateRconServerRequest(
            ip=ip,
            port=port,
            password=password,
            name=name,
            scheme=scheme,
            is_active=is_active,
            is_default=is_default
        )
        res = await self._request("POST", "/api/v1/rcon-servers", json=req.model_dump(exclude_none=True))
        return schemas.RconServerActionResponse(**res)

    async def get_rcon_server(self, server_id: int) -> schemas.RconServerItem:
        res = await self._request("GET", f"/api/v1/rcon-servers/{server_id}")
        return schemas.RconServerItem(**res)

    async def update_rcon_server(self, server_id: int, **kwargs) -> schemas.RconServerActionResponse:
        req = schemas.UpdateRconServerRequest(**kwargs)
        res = await self._request("PUT", f"/api/v1/rcon-servers/{server_id}", json=req.model_dump(exclude_unset=True))
        return schemas.RconServerActionResponse(**res)

    async def delete_rcon_server(self, server_id: int) -> schemas.RconServerActionResponse:
        res = await self._request("DELETE", f"/api/v1/rcon-servers/{server_id}")
        return schemas.RconServerActionResponse(**res)

    async def test_rcon_server(self, server_id: int) -> schemas.RconServerTestResponse:
        res = await self._request("POST", f"/api/v1/rcon-servers/{server_id}/test")
        return schemas.RconServerTestResponse(**res)

    async def sync_all_rcon_servers(self) -> schemas.RconServersSyncAllResponse:
        res = await self._request("POST", "/api/v1/rcon-servers/sync-all")
        return schemas.RconServersSyncAllResponse(**res)

    # Membership Types management endpoints
    async def get_membership_types(self, active_only: bool = False) -> list[schemas.MembershipTypeItem]:
        res = await self._request("GET", f"/api/v1/membership-types?active_only={active_only}")
        return [schemas.MembershipTypeItem(**item) for item in res]

    async def get_membership_type(self, identifier: int | str) -> schemas.MembershipTypeItem:
        res = await self._request("GET", f"/api/v1/membership-types/{identifier}")
        return schemas.MembershipTypeItem(**res)

    async def create_membership_type(self, **kwargs) -> schemas.MembershipTypeActionResponse:
        req = schemas.CreateMembershipTypeRequest(**kwargs)
        res = await self._request("POST", "/api/v1/membership-types", json=req.model_dump(exclude_none=True))
        return schemas.MembershipTypeActionResponse(**res)

    async def update_membership_type(self, type_id: int, **kwargs) -> schemas.MembershipTypeActionResponse:
        req = schemas.UpdateMembershipTypeRequest(**kwargs)
        res = await self._request("PUT", f"/api/v1/membership-types/{type_id}", json=req.model_dump(exclude_unset=True))
        return schemas.MembershipTypeActionResponse(**res)

    async def delete_membership_type(self, type_id: int) -> schemas.MembershipTypeActionResponse:
        res = await self._request("DELETE", f"/api/v1/membership-types/{type_id}")
        return schemas.MembershipTypeActionResponse(**res)

    # Rewards & Seeding
    async def get_rewards_catalog(self, only_active: bool = True) -> list[schemas.RewardItemResponse]:
        res = await self._request("GET", f"/api/v1/rewards/catalog?only_active={only_active}")
        return [schemas.RewardItemResponse(**i) for i in res]

    async def get_player_rewards_balance(self, identifier: str) -> schemas.PlayerRewardBalanceResponse:
        res = await self._request("GET", f"/api/v1/rewards/balance/{identifier}")
        return schemas.PlayerRewardBalanceResponse(**res)

    async def claim_reward(self, player_identifier: str, reward_code: str) -> schemas.RewardClaimResultResponse:
        payload = schemas.ClaimRewardRequest(player_identifier=player_identifier, reward_code=reward_code).model_dump()
        res = await self._request("POST", "/api/v1/rewards/claim", json=payload)
        return schemas.RewardClaimResultResponse(**res)

    async def create_or_update_reward_item(self, **kwargs) -> schemas.RewardItemResponse:
        req = schemas.CreateRewardItemRequest(**kwargs)
        res = await self._request("POST", "/api/v1/rewards/admin/create", json=req.model_dump(exclude_none=True))
        return schemas.RewardItemResponse(**res)

    async def verify_reward_claim(self, claim_code: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/rewards/admin/verify/{claim_code}")

    async def deliver_reward_claim(self, claim_code: str, delivered_by: str, notes: str | None = None) -> dict[str, Any]:
        payload = schemas.DeliverClaimRequest(delivered_by=delivered_by, notes=notes).model_dump()
        return await self._request("POST", f"/api/v1/rewards/admin/deliver/{claim_code}", json=payload)

    async def refund_reward_claim(self, claim_code: str, refunded_by: str, reason: str | None = None) -> dict[str, Any]:
        payload = schemas.RefundClaimRequest(refunded_by=refunded_by, reason=reason).model_dump()
        return await self._request("POST", f"/api/v1/rewards/admin/refund/{claim_code}", json=payload)

    async def give_reward_points(self, player_identifier: str, points: int, reason: str | None = None) -> dict[str, Any]:
        payload = schemas.GiveRewardPointsRequest(player_identifier=player_identifier, points=points, reason=reason).model_dump()
        return await self._request("POST", "/api/v1/rewards/admin/give_points", json=payload)

    # Squads
    async def create_squad(self, name: str, tag: str, leader_steam_id: str) -> schemas.SquadData:
        res = await self._request("POST", f"/api/v1/db/squads?name={name}&tag={tag}&leader_steam_id={leader_steam_id}")
        return schemas.SquadData(**res)

    async def get_squad_leaderboard(self, sort_by: str = "kills") -> list[schemas.SquadData]:
        res = await self._request("GET", f"/api/v1/db/squads/leaderboard?sort_by={sort_by}")
        return [schemas.SquadData(**x) for x in res]

    async def get_squad_internal_leaderboard(self, squad_id: str, sort_by: str = "kills") -> list[schemas.SquadMemberData]:
        res = await self._request("GET", f"/api/v1/db/squads/{squad_id}/internal-leaderboard?sort_by={sort_by}")
        return [schemas.SquadMemberData(**x) for x in res]

    async def get_player_squads(self, steam_id: str) -> list[schemas.SquadData]:
        res = await self._request("GET", f"/api/v1/db/squads/by-player/{steam_id}")
        return [schemas.SquadData(**x) for x in res]

    async def get_squad_by_tag(self, tag: str) -> schemas.SquadData:
        res = await self._request("GET", f"/api/v1/db/squads/by-tag/{tag}")
        return schemas.SquadData(**res)

    async def get_squad_members(self, squad_id: str) -> list[schemas.SquadMemberData]:
        res = await self._request("GET", f"/api/v1/db/squads/{squad_id}/members")
        return [schemas.SquadMemberData(**x) for x in res]

    async def add_squad_member(self, squad_id: str, steam_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/db/squads/{squad_id}/members?steam_id={steam_id}")

    async def remove_squad_member(self, squad_id: str, steam_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/v1/db/squads/{squad_id}/members/{steam_id}")

    async def disband_squad(self, squad_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/v1/db/squads/{squad_id}")
    async def get_expiring_memberships(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/db/memberships/expiring")
        
    async def mark_membership_notified(self, membership_id: int, notification_type: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/db/memberships/{membership_id}/mark_notified?notification_type={notification_type}")
