"""
Steam Web API client.

Uses a single persistent aiohttp.ClientSession per-process (lazy-initialised)
to avoid the overhead of opening a new TCP connection on every batch call.

The API key is read lazily from the environment so that it is always resolved
*after* load_dotenv() runs in main.py, fixing a silent bug where the module-level
``os.environ.get("STEAM_WEB_API_KEY")`` was evaluated before the .env file was
loaded and therefore always returned None.
"""
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger("wardogs.steam")

_STEAM_API_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
_CHUNK_SIZE = 100  # Steam API hard limit per request

# Module-level session, lazily created and reused across requests.
_session: aiohttp.ClientSession | None = None


def _get_api_key() -> str | None:
    """Reads STEAM_WEB_API_KEY from centralized config or environment."""
    from wardogs_config import ENVIRONMENT_SETTINGS
    return ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.STEAM_WEB_API_KEY or os.environ.get("STEAM_WEB_API_KEY")


async def _get_session() -> aiohttp.ClientSession:
    """Returns (or creates) the module-level aiohttp session."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def get_player_summary(steam_id: str) -> dict[str, Any] | None:
    """Returns the Steam profile summary for a single player, or None on failure."""
    summaries = await get_player_summaries([steam_id])
    return summaries.get(steam_id)


async def get_player_summaries(steam_ids: list[str]) -> dict[str, dict[str, Any]]:
    """
    Returns a ``{steamid: summary_dict}`` map for up to 100 Steam IDs per chunk.

    Silently returns an empty dict when no API key is configured or the list
    is empty, so callers do not need to guard against missing keys.
    """
    api_key = _get_api_key()
    if not api_key or not steam_ids:
        return {}

    session = await _get_session()
    results: dict[str, dict[str, Any]] = {}

    for i in range(0, len(steam_ids), _CHUNK_SIZE):
        chunk = steam_ids[i : i + _CHUNK_SIZE]
        params = {"key": api_key, "steamids": ",".join(chunk)}
        try:
            async with session.get(_STEAM_API_URL, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    players = data.get("response", {}).get("players", [])
                    for p in players:
                        results[p["steamid"]] = p
                else:
                    logger.warning(
                        "Steam API returned HTTP %s for chunk starting at index %d",
                        resp.status,
                        i,
                    )
        except Exception:
            logger.exception("Error fetching Steam profiles for chunk at index %d", i)

    return results
