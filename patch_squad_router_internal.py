import sys
with open("apps/api_rcon/src/modules/v1/routers/squads.py", "r", encoding="utf-8") as f:
    content = f.read()

new_route = """@router.get("/{squad_id}/internal-leaderboard", response_model=List[Dict[str, Any]])
async def get_squad_internal_leaderboard(squad_id: str, sort_by: str = "kills", session: AsyncSession = Depends(get_session)):
    return await SquadsService.get_squad_internal_leaderboard(squad_id, sort_by, session)

"""

content = content.replace("@router.post(\"/{squad_id}/members?steam_id={steam_id}\",", new_route + "@router.post(\"/{squad_id}/members?steam_id={steam_id}`,")

with open("apps/api_rcon/src/modules/v1/routers/squads.py", "w", encoding="utf-8") as f:
    f.write(content)
