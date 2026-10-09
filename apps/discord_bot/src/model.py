
from wardogs_config import BOT_SETTINGS, DiscordBotSettings

from src.api_client import APIClient


class Model:
    api: APIClient
    active_match_id: str
    players_cache: dict
    initial_scan_done: bool
    
    def __init__(self, settings: DiscordBotSettings | None = None):
        cfg = settings or BOT_SETTINGS
        self.api = APIClient(
            base_url=cfg.API_BASE_URL,
            api_key=cfg.API_KEY,
        )
        self.public_api_url = cfg.PUBLIC_API_URL
        self.active_match_id = ""
        self.players_cache = {}
        self.hacker_monitors = {}
        self.player_last_seen = {}
        self.initial_scan_done = False

