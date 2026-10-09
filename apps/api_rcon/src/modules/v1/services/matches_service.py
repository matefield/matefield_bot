from typing import Any

from fastapi import HTTPException
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import (
    Match,
    MatchPlayerStats,
    MatchTeamStats,
    Player,
    Team,
)


class MatchesService:
    @staticmethod
    async def get_paginated_matches(page: int, limit: int, session: AsyncSession) -> dict[str, Any]:
        offset = max(0, (page - 1) * limit)
        statement = select(Match).order_by(col(Match.start_time).desc()).offset(offset).limit(limit)
        matches = (await session.exec(statement)).all()
        
        total_statement = select(func.count(col(Match.id)))
        total = (await session.exec(total_statement)).one()
        
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "matches": [
                {
                    "id": m.id, 
                    "map": m.map_name, 
                    "start_time": m.start_time.isoformat(),
                    "end_time": m.end_time.isoformat() if m.end_time else None
                } 
                for m in matches
            ]
        }

    @staticmethod
    async def get_latest_match(session: AsyncSession) -> dict[str, Any]:
        statement = select(Match).where(Match.end_time != None).order_by(col(Match.end_time).desc())
        match = (await session.exec(statement)).first()
        
        if not match:
            raise HTTPException(status_code=404, detail="No completed matches found")
            
        team_stats_stmt = select(MatchTeamStats, Team).join(Team).where(MatchTeamStats.match_id == match.id)
        team_stats = (await session.exec(team_stats_stmt)).all()
        
        player_stats_stmt = select(MatchPlayerStats).where(MatchPlayerStats.match_id == match.id)
        player_stats = (await session.exec(player_stats_stmt)).all()
        
        return {
            "id": match.id,
            "map": match.map_name,
            "start_time": match.start_time.isoformat(),
            "end_time": match.end_time.isoformat() if match.end_time else None,
            "winning_team_id": match.winning_team_id,
            "team_stats": [
                {
                    "team_id": ts.team_id,
                    "team_name": team.name,
                    "team_code": team.code,
                    "score": ts.score
                }
                for ts, team in team_stats
            ],
            "player_stats": [
                {
                    "steam_id": ps.steam_id,
                    "team_id": ps.team_id,
                    "kills": ps.kills,
                    "deaths": ps.deaths,
                    "cash_earned": ps.cash_earned
                }
                for ps in player_stats
            ]
        }

    @staticmethod
    async def get_leaderboard(metric: str, limit: int, session: AsyncSession) -> dict[str, Any]:
        valid_metrics = {
            "kills": MatchPlayerStats.kills, 
            "deaths": MatchPlayerStats.deaths, 
            "cash_earned": MatchPlayerStats.cash_earned
        }
        
        if metric not in valid_metrics:
            raise HTTPException(status_code=400, detail="Invalid metric")
            
        metric_col = valid_metrics[metric]
        
        statement = (
            select(MatchPlayerStats.steam_id, Player.discord_id, func.sum(metric_col).label("total"))
            .join(Player, col(MatchPlayerStats.steam_id) == col(Player.steam_id))
            .group_by(col(MatchPlayerStats.steam_id), col(Player.discord_id))
            .order_by(func.sum(metric_col).desc())
            .limit(limit)
        )
        
        results = (await session.exec(statement)).all()
        
        return {
            "metric": metric,
            "leaderboard": [
                {"steam_id": row[0], "discord_id": row[1], "total": int(row[2]) if row[2] else 0}
                for row in results
            ]
        }
