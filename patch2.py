with open("apps/discord_bot/src/api_client.py", "r", encoding="utf-8") as f:
    content = f.read()

new_str = """    async def get_player_squads(self, steam_id: str) -> List[Dict[str, Any]]:
        return await self._request("GET", f"/api/v1/db/squads/by-player/{steam_id}")

    async def get_squad_by_tag(self, tag: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/v1/db/squads/by-tag/{tag}")"""

content = content.replace(
    """    async def get_player_squads(self, steam_id: str) -> List[Dict[str, Any]]:
        return await self._request("GET", f"/api/v1/db/squads/by-player/{steam_id}")""",
    new_str
)

with open("apps/discord_bot/src/api_client.py", "w", encoding="utf-8") as f:
    f.write(content)
