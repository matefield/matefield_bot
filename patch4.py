import sys
with open("apps/discord_bot/src/plugins/squads.py", "r", encoding="utf-8") as f:
    content = f.read()

autocomplete_code = """async def squad_autocomplete(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    try:
        player = await plugin.model.api.get_player_by_discord(str(ctx.user.id))
        steam_id = player.get("steam_id")
        if not steam_id:
            return []
        squads = await plugin.model.api.get_player_squads(steam_id)
        val = str(option.value or "").strip().lower()
        results = []
        for sq in squads:
            label = f"[{sq['tag']}] {sq['name']}"
            if not val or val in label.lower() or val in sq['tag'].lower():
                results.append((label, sq['tag']))
        return results[:25]
    except Exception:
        return []

"""

content = content.replace(
    "async def get_steam_id_from_member", 
    autocomplete_code + "async def get_steam_id_from_member"
)

# Now add autocomplete=squad_autocomplete to all `unidad` options
old_unidad = "unidad = crescent.option(str, \"Tag del pelotón (si estás en varios)\", default=None)"
new_unidad = "unidad = crescent.option(str, \"Tag del pelotón (si estás en varios)\", default=None, autocomplete=squad_autocomplete)"
content = content.replace(old_unidad, new_unidad)

old_unidad_2 = "unidad = crescent.option(str, \"Tag del pelotón (opcional)\", default=None)"
new_unidad_2 = "unidad = crescent.option(str, \"Tag del pelotón (opcional)\", default=None, autocomplete=squad_autocomplete)"
content = content.replace(old_unidad_2, new_unidad_2)

with open("apps/discord_bot/src/plugins/squads.py", "w", encoding="utf-8") as f:
    f.write(content)
