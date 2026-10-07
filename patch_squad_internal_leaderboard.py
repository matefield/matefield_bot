import sys
with open("apps/api_rcon/src/modules/v1/services/squads_service.py", "r", encoding="utf-8") as f:
    content = f.read()

new_code = """    @staticmethod
    async def get_squad_internal_leaderboard(squad_id: str, sort_by: str, session: AsyncSession) -> List[Dict[str, Any]]:
        # Obtiene todos los miembros del pelotón y suma sus estadísticas históricas
        from src.connections.databases.db import MatchPlayerStats
        
        members = await SquadsService.get_squad_members(squad_id, session)
        if not members:
            return []
            
        steam_ids = [m.steam_id for m in members]
        
        # Agrupar estadísticas por jugador
        query = (
            select(
                MatchPlayerStats.steam_id,
                func.sum(MatchPlayerStats.kills).label("total_kills"),
                func.sum(MatchPlayerStats.deaths).label("total_deaths"),
                func.sum(MatchPlayerStats.cash_earned).label("total_cash_earned")
            )
            .where(col(MatchPlayerStats.steam_id).in_(steam_ids))
            .group_by(MatchPlayerStats.steam_id)
        )
        
        stats_rows = (await session.exec(query)).all()
        stats_map = {row.steam_id: row for row in stats_rows}
        
        results = []
        for m in members:
            st = stats_map.get(m.steam_id)
            results.append({
                "steam_id": m.steam_id,
                "in_game_name": m.in_game_name,
                "kills": getattr(st, "total_kills", 0) or 0,
                "deaths": getattr(st, "total_deaths", 0) or 0,
                "cash": getattr(st, "total_cash_earned", 0) or 0
            })
            
        if sort_by == "deaths":
            results.sort(key=lambda x: x["deaths"], reverse=True)
        elif sort_by == "cash":
            results.sort(key=lambda x: x["cash"], reverse=True)
        else:
            results.sort(key=lambda x: x["kills"], reverse=True)
            
        return results
"""

content += "\n" + new_code

with open("apps/api_rcon/src/modules/v1/services/squads_service.py", "w", encoding="utf-8") as f:
    f.write(content)
