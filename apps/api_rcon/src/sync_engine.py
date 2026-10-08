"""
Sync Engine — continuous RCON polling and game-state synchronisation.

Responsibilities:
- Detect match transitions (start / end) via rotation index changes.
- Upsert ``Player``, ``MatchPlayerStats``, and ``Team`` rows per tick.
- Track per-player ``PlayerSession`` durations and award seeding reward points.
- Update team scores and detect match completion when score_cap is reached.
- Fetch Steam avatar / persona name in a fire-and-forget background task.

All heavy I/O is routed through the active default RCON server resolved from
the database (``RCONManager.get_default_server``), falling back to the .env
configuration when no DB server rows exist.
"""
import asyncio
import datetime
import logging
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.apis.rcon import RCONManager
from src.connections.databases.db import (
    BotConfig,
    Match,
    MatchPlayerStats,
    MatchTeamStats,
    Player,
    PlayerSession,
    Team,
    engine,
)
from src.modules.v1.services.rewards_service import RewardsService


class SyncEngineState:
    """Encapsulates the in-memory state of match tracking and map rotations."""
    def __init__(self):
        self.current_rotation_index: int | None = None
        self.current_match_id: str | None = None
        self.current_map: str | None = None
        self.empty_since: datetime.datetime | None = None
        self.has_unvalidated_seeding_campaign: bool = True

default_sync_state = SyncEngineState()
_server_sync_states: dict[int, SyncEngineState] = {}

# Polling and game sync constants
MAX_TIME_GAP_SECONDS = 60
DEFAULT_POLL_INTERVAL_SECONDS = 10
FAST_POLL_INTERVAL_SECONDS = 3
FAST_POLL_TICKS_REMAINING = 3
DEFAULT_SEEDING_MIN_PLAYERS = 20
DEFAULT_SEEDING_MINUTES_PER_POINT = 30
DEFAULT_SCORE_CAP = 100

logger = logging.getLogger("wardogs.sync_engine")


async def _get_int_config(session: AsyncSession, key: str, default: int) -> int:
    """Reads a numeric configuration from BotConfig with safe fallback."""
    cfg = await session.get(BotConfig, key)
    if cfg and cfg.config_value:
        try:
            return int(cfg.config_value)
        except (ValueError, TypeError):
            pass
    return default


async def _get_or_create_team(session: AsyncSession, faction_name: str | None) -> int | None:
    """Resolves or inserts a Team entity by name or short 3-letter code."""
    if not faction_name:
        return None
    name = str(faction_name).strip()
    if not name:
        return None
    team = (await session.exec(select(Team).where(Team.name == name))).first()
    if not team:
        code = name[:3].upper() if len(name) >= 3 else name.upper()
        existing_code = (await session.exec(select(Team).where(Team.code == code))).first()
        if existing_code:
            code = f"{name[:2].upper()}{len(name)}"[:3]
        team = Team(name=name, code=code)
        session.add(team)
        await session.flush()
        await session.refresh(team)
    return team.id


async def _fetch_avatars_background(steam_ids: list[str]):
    try:
        from src.connections.apis.steam import get_player_summaries
        summaries = await get_player_summaries(steam_ids)
        if summaries:
            async with AsyncSession(engine) as s:
                changed_any = False
                for steam_id, summary in summaries.items():
                    avatar = summary.get("avatarfull") or summary.get("avatarmedium")
                    personaname = summary.get("personaname")
                    if avatar or personaname:
                        p = await s.get(Player, steam_id)
                        if p:
                            if avatar and not p.avatar_url:
                                p.avatar_url = avatar
                                changed_any = True
                            if personaname and not p.in_game_name:
                                p.in_game_name = personaname
                                changed_any = True
                            if changed_any:
                                s.add(p)
                if changed_any:
                    await s.commit()
    except Exception as e: # noqa: BLE001
        logger.debug(f"[Sync Engine] Could not fetch steam profiles for chunk: {e}")


async def process_sync_tick(
    session: AsyncSession,
    status: Any,
    players: Any,
    now: datetime.datetime,
    delta_seconds: int,
    state: SyncEngineState | None = None,
) -> dict[str, Any]:
    """
    Processes a single game server polling tick:
    1. Handles match rotation & start/end lifecycle.
    2. Upserts connected player records and match player statistics.
    3. Manages player sessions and calculates seeding rewards (runs even if 0 players online to close sessions).
    4. Tracks team scores and detects match win/completion.
    """
    if state is None:
        state = default_sync_state

    rotation_index = status.rotation.nowIndex if (status and status.rotation) else None
    map_name = (status.map if status else None) or "Unknown"

    # 1. Check for match start/transition
    match_transitioned = False
    if state.current_match_id is None or rotation_index != state.current_rotation_index:
        logger.info(f"[Match Engine] Match transition! Old map: {state.current_map}, New map: {map_name} (Rotation {rotation_index})")
        match_transitioned = True
        
        # Close old match if it exists and hasn't been closed yet
        if state.current_match_id:
            old_match = await session.get(Match, state.current_match_id)
            if old_match and old_match.end_time is None:
                old_match.end_time = now
                winner_stmt = select(MatchTeamStats).where(MatchTeamStats.match_id == state.current_match_id).order_by(col(MatchTeamStats.score).desc())
                winner_stat = (await session.exec(winner_stmt)).first()
                if winner_stat:
                    old_match.winning_team_id = winner_stat.team_id
                session.add(old_match)

        # Start new match
        match_seconds = (status.matchSeconds or 0) if status else 0
        real_start_time = now - datetime.timedelta(seconds=match_seconds)
        new_match = Match(
            map_name=map_name,
            start_time=real_start_time
        )
        session.add(new_match)
        await session.flush()
        
        state.current_match_id = new_match.id
        state.current_rotation_index = rotation_index
        state.current_map = map_name

    # 2. Sync players & player stats
    from src.connections.databases.db import SquadMember
    current_players_list = players.players if (players and players.players) else []
    
    # Pre-fetch squad memberships for active players to avoid N queries
    squad_memberships = {}
    if current_players_list:
        active_steam_ids = [p.steamId for p in current_players_list if p.steamId]
        squad_mems = (await session.exec(select(SquadMember).where(col(SquadMember.steam_id).in_(active_steam_ids)))).all()
        squad_memberships = {m.steam_id: m.squad_id for m in squad_mems}

    for p in current_players_list:
        if not p.steamId:
            continue
            
        db_player = await session.get(Player, p.steamId)
        if not db_player:
            db_player = Player(steam_id=p.steamId, discord_id=None, in_game_name=p.name)
            session.add(db_player)
            await session.flush()
        elif p.name and db_player.in_game_name != p.name:
            db_player.in_game_name = p.name
            session.add(db_player)
            
        if state.current_match_id:
            team_id = await _get_or_create_team(session, p.faction)
            current_squad_id = squad_memberships.get(p.steamId)
            stmt = select(MatchPlayerStats).where(
                MatchPlayerStats.match_id == state.current_match_id,
                MatchPlayerStats.steam_id == p.steamId
            )
            stats = (await session.exec(stmt)).first()
            if not stats:
                stats = MatchPlayerStats(
                    match_id=state.current_match_id,
                    steam_id=p.steamId,
                    team_id=team_id,
                    squad_id=current_squad_id,
                    kills=p.kills or 0,
                    deaths=p.deaths or 0,
                    cash_earned=p.cash or 0
                )
            else:
                stats.kills = p.kills or 0
                stats.deaths = p.deaths or 0
                stats.team_id = team_id
                stats.squad_id = current_squad_id
                current_cash = p.cash or 0
                stats.cash_earned = max(stats.cash_earned, current_cash)
            session.add(stats)

    # 3. Session Tracking is now moved out to be processed globally

    # 4. Match Team Stats & End Detection
    match_ended = False
    if state.current_match_id and status and status.factionScores:
        score_cap = status.scoreCap or DEFAULT_SCORE_CAP
        match_record = await session.get(Match, state.current_match_id)
        if match_record and match_record.end_time is None:
            max_score = 0
            winning_team_id = None
            
            for fs in status.factionScores:
                if not fs.name:
                    continue
                team_id = await _get_or_create_team(session, fs.name)
                if not team_id:
                    continue
                    
                ts_stmt = select(MatchTeamStats).where(
                    MatchTeamStats.match_id == state.current_match_id,
                    MatchTeamStats.team_id == team_id
                )
                t_stat = (await session.exec(ts_stmt)).first()
                score_val = int(fs.score or 0)
                if not t_stat:
                    t_stat = MatchTeamStats(match_id=state.current_match_id, team_id=team_id, score=score_val)
                    session.add(t_stat)
                else:
                    t_stat.score = score_val
                    session.add(t_stat)
                    
                if score_val >= max_score:
                    max_score = score_val
                    winning_team_id = team_id
                    
            if max_score >= score_cap:
                logger.info(f"[Match Engine] Match ended! Score {max_score} >= {score_cap}")
                match_record.end_time = now
                match_record.winning_team_id = winning_team_id
                session.add(match_record)
                match_ended = True
                
                # --- Update Squad Stats ---
                try:
                    from src.connections.databases.db import Squad, SquadMember
                    match_stats = (await session.exec(select(MatchPlayerStats).where(MatchPlayerStats.match_id == state.current_match_id))).all()
                    updated_squads = set()
                    
                    for ms in match_stats:
                        squad_mem = (await session.exec(select(SquadMember).where(SquadMember.steam_id == ms.steam_id))).first()
                        if squad_mem:
                            squad = await session.get(Squad, squad_mem.squad_id)
                            if squad:
                                squad.total_kills += ms.kills
                                squad.total_deaths += ms.deaths
                                squad.total_cash_earned += ms.cash_earned
                                if squad.id not in updated_squads:
                                    squad.total_matches_played += 1
                                    updated_squads.add(squad.id)
                                session.add(squad)
                except Exception as sq_err: # noqa: BLE001
                    logger.error(f"[Match Engine] Error updating squad stats: {sq_err}")
                # -------------------------

    await session.commit()
    return {
        "match_id": state.current_match_id,
        "match_transitioned": match_transitioned,
        "match_ended": match_ended,
        "active_players_count": len(current_players_list),
        "is_seeding": False,
    }


async def poll_rcon(state: SyncEngineState | None = None):
    """Continuous polling loop querying game server status and processing sync ticks."""
    if state is None:
        state = default_sync_state
    
    logger.info("Starting RCON Polling Engine...")
    last_poll_time = datetime.datetime.now(datetime.UTC)
    
    while True:
        try:
            now = datetime.datetime.now(datetime.UTC)
            delta_seconds = int((now - last_poll_time).total_seconds())
            
            if delta_seconds < 0:
                logger.warning("[Match Engine] Negative time gap detected (%ds). Clock drift? Resetting.", delta_seconds)
                delta_seconds = 0
                last_poll_time = now
            elif delta_seconds > MAX_TIME_GAP_SECONDS:
                logger.warning(
                    "[Match Engine] Large time gap detected (%ds). Capping to %ds.",
                    delta_seconds,
                    MAX_TIME_GAP_SECONDS,
                )
                delta_seconds = MAX_TIME_GAP_SECONDS
                
            last_poll_time = now
            
            global_current_steam_ids = set()
            seeding_servers_steam_ids = set()
            player_to_server = {}
            
            async with AsyncSession(engine, expire_on_commit=False) as session:
                seeding_threshold = await _get_int_config(session, "SEEDING_MIN_PLAYERS", DEFAULT_SEEDING_MIN_PLAYERS)
                seeding_min_to_count = await _get_int_config(session, "SEEDING_MIN_PLAYERS_TO_COUNT", 4)
                minutes_per_point = await _get_int_config(session, "SEEDING_MINUTES_PER_POINT", DEFAULT_SEEDING_MINUTES_PER_POINT)
                
                active_servers = await RCONManager.get_all_active_servers(session)
                
                states = _server_sync_states

                sleep_time = DEFAULT_POLL_INTERVAL_SECONDS

                for server, client in active_servers:
                    s_id = server.id or 0
                    if s_id not in states:
                        states[s_id] = SyncEngineState()
                    state = states[s_id]
                    
                    try:
                        status = await client.get_status()
                        players = await client.get_players()
                        
                        await process_sync_tick(session, status, players, now, delta_seconds, state=state)
                        
                        # Collect global sessions data
                        current_players_list = players.players if (players and players.players) else []
                        current_players_count = (status.players.current or 0) if (status and status.players) else len(current_players_list)
                        is_seeding = current_players_count < seeding_threshold and current_players_count >= seeding_min_to_count
                        
                        for p in current_players_list:
                            if p.steamId:
                                global_current_steam_ids.add(p.steamId)
                                player_to_server[p.steamId] = s_id
                                if is_seeding:
                                    seeding_servers_steam_ids.add(p.steamId)

                        # --- Seeding Campaign Evaluation ---
                        await RewardsService.process_server_seeding_campaign(
                            session=session,
                            server_id=s_id,
                            state=state,
                            current_players_count=current_players_count,
                            is_seeding=is_seeding,
                            seeding_threshold=seeding_threshold,
                            seeding_min_to_count=seeding_min_to_count,
                            minutes_per_point=minutes_per_point,
                            now=now
                        )
                        # ------------------------------------

                        if status and status.scoreTick and status.scoreCap:
                            tick_current = status.scoreTick.current or 0
                            if tick_current >= (status.scoreCap - FAST_POLL_TICKS_REMAINING):
                                sleep_time = FAST_POLL_INTERVAL_SECONDS
                                
                    except Exception as e: # noqa: BLE001
                        logger.error(f"[Match Engine] Error polling server {server.name}: {e}")
                
                # Global Session Tracking
                active_sessions_stmt = select(PlayerSession).where(PlayerSession.end_time == None).order_by(col(PlayerSession.id))
                active_sessions = (await session.exec(active_sessions_stmt)).all()
                active_session_dict = {s.steam_id: s for s in active_sessions}

                for s in active_sessions:
                    if s.steam_id in global_current_steam_ids:
                        current_server_id_for_player = player_to_server.get(s.steam_id)
                        if s.server_id != current_server_id_for_player:
                            # Player changed servers without disconnecting! Close old session.
                            s.end_time = s.start_time + datetime.timedelta(seconds=s.total_seconds)
                            session.add(s)
                            del active_session_dict[s.steam_id]
                        else:
                            # Player is online and on the same server
                            s.total_seconds += delta_seconds
                            if s.steam_id in seeding_servers_steam_ids:
                                s.seeding_seconds += delta_seconds
                            session.add(s)
                    else:
                        # Player disconnected
                        s.end_time = s.start_time + datetime.timedelta(seconds=s.total_seconds)
                        session.add(s)

                new_sids_for_avatar = []
                for sid in global_current_steam_ids:
                    if sid not in active_session_dict:
                        p_exists = await session.get(Player, sid)
                        if not p_exists:
                            session.add(Player(steam_id=sid))
                            await session.flush()
                        srv_id = player_to_server.get(sid)
                        new_sess = PlayerSession(steam_id=sid, server_id=srv_id, start_time=now)
                        session.add(new_sess)
                        new_sids_for_avatar.append(sid)
                
                if new_sids_for_avatar:
                    asyncio.create_task(_fetch_avatars_background(new_sids_for_avatar))
                
                await session.commit()

            await asyncio.sleep(sleep_time)

        except Exception as e: # noqa: BLE001
            logger.exception("[Match Engine] Error polling RCON in sync_engine: %s", e)
            await asyncio.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
