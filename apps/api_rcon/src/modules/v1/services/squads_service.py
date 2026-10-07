import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlmodel import select, col, func
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Squad, SquadMember, SquadInvite, Player

logger = logging.getLogger("wardogs.squads")

class SquadsService:
    @staticmethod
    async def create_squad(name: str, tag: str, leader_steam_id: str, session: AsyncSession) -> Squad:
        name = name.strip()
        tag = tag.strip().upper()
        
        if len(name) < 3 or len(name) > 32:
            raise HTTPException(status_code=400, detail="El nombre debe tener entre 3 y 32 caracteres.")
        if len(tag) < 2 or len(tag) > 4:
            raise HTTPException(status_code=400, detail="El tag debe tener entre 2 y 4 caracteres.")
        
        
        # Check if player already owns or is in a squad
        existing_member = (await session.exec(select(SquadMember).where(SquadMember.steam_id == leader_steam_id))).first()
        if existing_member:
            raise HTTPException(status_code=400, detail="Ya perteneces a un pelotón.")
        
        # Check if name or tag is taken
        existing_squad = (await session.exec(
            select(Squad).where((func.upper(Squad.name) == name.upper()) | (func.upper(Squad.tag) == tag))
        )).first()
        
        if existing_squad:
            raise HTTPException(status_code=400, detail="El nombre o tag del pelotón ya está en uso.")
        
        # Create squad
        new_squad = Squad(name=name, tag=tag, leader_steam_id=leader_steam_id)
        session.add(new_squad)
        await session.flush()
        
        # Add leader as member
        leader_member = SquadMember(squad_id=new_squad.id, steam_id=leader_steam_id)
        session.add(leader_member)
        await session.commit()
        await session.refresh(new_squad)
        
        return new_squad

    @staticmethod
    async def get_squad(squad_id: str, session: AsyncSession) -> Squad:
        squad = (await session.exec(select(Squad).where(Squad.id == squad_id))).first()
        if not squad:
            raise HTTPException(status_code=404, detail="Pelotón no encontrado.")
        return squad

    @staticmethod
    async def get_squad_by_name_or_tag(query: str, session: AsyncSession) -> Squad:
        query_upper = query.strip().upper()
        squad = (await session.exec(
            select(Squad).where((func.upper(Squad.name) == query_upper) | (func.upper(Squad.tag) == query_upper))
        )).first()
        if not squad:
            raise HTTPException(status_code=404, detail="Pelotón no encontrado.")
        return squad

    @staticmethod
    async def get_player_squads(steam_id: str, session: AsyncSession) -> List[Squad]:
        members = (await session.exec(select(SquadMember).where(SquadMember.steam_id == steam_id))).all()
        if not members:
            return []
        
        squad_ids = [m.squad_id for m in members]
        squads = (await session.exec(select(Squad).where(col(Squad.id).in_(squad_ids)))).all()
        return squads

    @staticmethod
    async def get_squad_members(squad_id: str, session: AsyncSession) -> List[Player]:
        # Returns the players in a squad
        members = (await session.exec(select(SquadMember).where(SquadMember.squad_id == squad_id))).all()
        if not members:
            return []
            
        steam_ids = [m.steam_id for m in members]
        players = (await session.exec(select(Player).where(col(Player.steam_id).in_(steam_ids)))).all()
        return players

    @staticmethod
    async def add_member(squad_id: str, steam_id: str, session: AsyncSession) -> SquadMember:
        # Check if squad exists
        await SquadsService.get_squad(squad_id, session)

        # Check if already in a squad
        existing = (await session.exec(select(SquadMember).where(SquadMember.steam_id == steam_id))).first()
        if existing:
            raise HTTPException(status_code=400, detail="El jugador ya pertenece a un pelotón.")
        
        member = SquadMember(squad_id=squad_id, steam_id=steam_id)
        session.add(member)
        await session.commit()
        return member

    @staticmethod
    async def remove_member(squad_id: str, steam_id: str, session: AsyncSession):
        squad = await SquadsService.get_squad(squad_id, session)
        if squad.leader_steam_id == steam_id:
            raise HTTPException(status_code=400, detail="El líder no puede salir del pelotón. Debe disolverlo primero.")
            
        member = (await session.exec(select(SquadMember).where(SquadMember.squad_id == squad_id, SquadMember.steam_id == steam_id))).first()
        if member:
            await session.delete(member)
            await session.commit()

    @staticmethod
    async def disband_squad(squad_id: str, session: AsyncSession):
        squad = await SquadsService.get_squad(squad_id, session)
        
        # Remove members
        members = (await session.exec(select(SquadMember).where(SquadMember.squad_id == squad_id))).all()
        for m in members:
            await session.delete(m)
            
        # Remove pending invites
        invites = (await session.exec(select(SquadInvite).where(SquadInvite.squad_id == squad_id))).all()
        for i in invites:
            await session.delete(i)
            
        await session.delete(squad)
        await session.commit()

    @staticmethod
    async def get_leaderboard(sort_by: str, session: AsyncSession, limit: int = 10) -> List[Squad]:
        order_col = col(Squad.total_kills).desc()
        if sort_by == "deaths":
            order_col = col(Squad.total_deaths).desc()
        elif sort_by == "cash":
            order_col = col(Squad.total_cash_earned).desc()
        elif sort_by == "matches":
            order_col = col(Squad.total_matches_played).desc()
            
        return (await session.exec(
            select(Squad).order_by(order_col).limit(limit)
        )).all()

    @staticmethod
    async def get_squad_internal_leaderboard(squad_id: str, sort_by: str, session: AsyncSession) -> List[Dict[str, Any]]:
        # Obtiene las estadísticas históricas con este equipo
        from src.connections.databases.db import MatchPlayerStats, Player
        
        members = await SquadsService.get_squad_members(squad_id, session)
        if not members:
            return []
            
        # Agrupar estadísticas por jugador filtrando por el squad_id
        query = (
            select(
                MatchPlayerStats.steam_id,
                func.sum(MatchPlayerStats.kills).label("total_kills"),
                func.sum(MatchPlayerStats.deaths).label("total_deaths"),
                func.sum(MatchPlayerStats.cash_earned).label("total_cash_earned")
            )
            .where(MatchPlayerStats.squad_id == squad_id)
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
            
        # Add ex-members that are not in the squad anymore but have stats
        current_member_ids = {m.steam_id for m in members}
        for row in stats_rows:
            if row.steam_id not in current_member_ids:
                # Fetch their name from the DB
                ex_player = await session.get(Player, row.steam_id)
                name = ex_player.in_game_name if ex_player else "Ex-Miembro"
                results.append({
                    "steam_id": row.steam_id,
                    "in_game_name": f"{name} (Retirado)",
                    "kills": row.total_kills or 0,
                    "deaths": row.total_deaths or 0,
                    "cash": row.total_cash_earned or 0
                })
            
        if sort_by == "deaths":
            results.sort(key=lambda x: x["deaths"], reverse=True)
        elif sort_by == "cash":
            results.sort(key=lambda x: x["cash"], reverse=True)
        else:
            results.sort(key=lambda x: x["kills"], reverse=True)
            
        return results
