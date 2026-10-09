import asyncio
import logging
import time
from typing import Any

import crescent
import hikari
from crescent.ext import tasks

from src.model import Model

plugin = crescent.Plugin[hikari.GatewayBot, Model]()
logger = logging.getLogger("wardogs.tasks")

# Task & Bot Automation Constants
DEFAULT_MVP_MEMBERSHIP_TYPE = "VIP_MVP_GIFT"
DEFAULT_MVP_DAYS = 1
VIP_BROADCAST_COOLDOWN_SECONDS = 300
VIP_BROADCAST_DELAY_SECONDS = 4
PLAYER_LAST_SEEN_PRUNE_SECONDS = 3600

# Embed UI Colors
COLOR_GOLD = 0xF1C40F
COLOR_BLUE = 0x3498DB
COLOR_GREEN = 0x2ECC71
COLOR_RED = 0xE74C3C
COLOR_GRAY = 0x95A5A6

def get_next_map(current_map: str, rotation: Any = None) -> str:
    """Calcula el nombre del próximo mapa según rotación o secuencia conocida."""
    prod_chain = {
        "bakurani": "Ozeti",
        "ozeti": "Zestafona",
        "zestafona": "Bakurani"
    }
    cur_norm = current_map.strip().lower()
    if cur_norm in prod_chain:
        return prod_chain[cur_norm]

    next_idx = getattr(rotation, "nextIndex", None) if rotation else None
    if next_idx is not None:
        standard_rotation = ["Zestafona", "Bakurani", "Ozeti"]
        return standard_rotation[next_idx % len(standard_rotation)]

    return "Siguiente"


def format_match_presence(status: Any | None, match_ended: bool = False, next_map: str | None = None) -> str:
    """
    Genera el estado contextual del bot para Discord sin emojis y máx 35 caracteres.
    - Contempla las 3 facciones: Lonestar (L), Valkyra (V) y Manticore (M).
    - Servidor lleno muestra '100/100' y vacío '0/100'.
    - Al terminar la partida menciona el próximo mapa en lugar del MVP.
    """
    if not status:
        return "Mantenimiento / Reiniciando"[:35]

    current_map = str((status.get("map") if isinstance(status, dict) else getattr(status, "map", None)) or "Wardogs").strip()

    # 1. Fin de partida: menciona el próximo mapa
    if match_ended:
        rot = status.get("rotation") if isinstance(status, dict) else getattr(status, "rotation", None)
        nxt = next_map or get_next_map(current_map, rot)
        res = f"Fin: {current_map[:10]} | Prox: {nxt[:10]}"
        return res[:35]

    players = status.get("players") if isinstance(status, dict) else getattr(status, "players", None)
    if isinstance(players, dict):
        cur_p = int(players.get("current") or 0)
        max_p = int(players.get("max") or 100)
    else:
        cur_p = int(getattr(players, "current", 0) or 0)
        max_p = int(getattr(players, "max", 100) or 100)

    # 2. Servidor vacío o con pocos jugadores
    if cur_p == 0:
        return f"{current_map} 0/{max_p}"[:35]
    if cur_p < 15:
        return f"{current_map} {cur_p}/{max_p}"[:35]

    # Extraer puntuación de las 3 facciones (Lonestar, Valkyra, Manticore)
    fscores = (status.get("factionScores") if isinstance(status, dict) else getattr(status, "factionScores", None)) or []
    scores: dict[str, int] = {}
    for fs in fscores:
        if isinstance(fs, dict):
            fname = str(fs.get("name") or fs.get("faction") or "").strip().lower()
            fscore = int(fs.get("score") or 0)
        else:
            fname = str(getattr(fs, "name", None) or getattr(fs, "faction", None) or "").strip().lower()
            fscore = int(getattr(fs, "score", 0) or 0)
        if fname.startswith("lone"):
            scores["L"] = fscore
        elif fname.startswith("valk"):
            scores["V"] = fscore
        elif fname.startswith("manti"):
            scores["M"] = fscore

    has_scores = bool(scores and any(v > 0 for v in scores.values()))
    score_str = f"L{scores.get('L', 0)} V{scores.get('V', 0)} M{scores.get('M', 0)}" if has_scores else ""

    # 3. Combate normal activo con los 3 equipos
    if score_str:
        res = f"{current_map} [{cur_p}/{max_p}] {score_str}"
        if len(res) <= 35:
            return res
        return f"{current_map[:8]} [{cur_p}/{max_p}] {score_str}"[:35]

    # Servidor sin marcadores activos aún (calentamiento, espera o lleno)
    return f"{current_map} {cur_p}/{max_p}"[:35]


# Tarea de monitoreo de partida
@plugin.include
@tasks.loop(seconds=10)
async def match_monitor():
    if not plugin.model.api:
        return
        
    try:
        status = await plugin.model.api.get_status()
        
        score_cap = status.scoreCap or 100
        current_tick = status.scoreTick.current if status.scoreTick and status.scoreTick.current is not None else 0
        
        # Verificar si se alcanzo el limite de puntos
        match_ended = current_tick >= score_cap
        
        current_map = status.map or "Unknown"
        now_index = status.rotation.nowIndex if status.rotation else 0
        match_identifier = f"{current_map}_{now_index}"
        
        logger.debug(f"[Match Monitor] Revisando estado: Mapa={current_map}, Tick={current_tick}/{score_cap}, Tiempo Restante={status.matchSeconds}s")
        
        # Si acaba de terminar y no lo hemos procesado
        if match_ended and plugin.model.active_match_id != f"{match_identifier}_ended":
            logger.info(f"[Match Monitor] 🏆 ¡PARTIDA TERMINADA en {current_map}! (ID: {match_identifier})")
            plugin.model.active_match_id = f"{match_identifier}_ended"
            
            # Obtener a los jugadores
            players_data = await plugin.model.api.get_players()
            players = players_data.players or []
            
            if players:
                # El mejor jugador
                players.sort(key=lambda x: x.kills or 0, reverse=True)
                mvp = players[0]
                mvp_name = mvp.name or "Unknown"
                mvp_steam = mvp.steamId or ""
                
                logger.info(f"[Match Monitor] 🏅 MVP Detectado: {mvp_name} ({mvp_steam}) con {mvp.kills} kills.")
                
                # Regalar VIP al MVP
                if mvp_steam:
                    membership_type = await plugin.model.api.get_bot_config("MVP_MEMBERSHIP_TYPE") or DEFAULT_MVP_MEMBERSHIP_TYPE
                    days_str = await plugin.model.api.get_bot_config("MVP_MEMBERSHIP_DAYS")
                    try:
                        membership_days = int(days_str) if days_str and days_str.isdigit() else DEFAULT_MVP_DAYS
                    except Exception:
                        membership_days = DEFAULT_MVP_DAYS

                    await plugin.model.api.add_membership(mvp_steam, membership_type, membership_days)
                    logger.info(f"[Match Monitor] 🎁 Membresía VIP de {membership_days} día(s) otorgada a {mvp_name}.")
                    
                    # Anunciar en RCON
                    await plugin.model.api.broadcast(f"¡Partida terminada! MVP: {mvp_name}. ¡Ha ganado {membership_days} día(s) de VIP!")
                    
                    # Anunciar en Discord
                    channel_id_str = await plugin.model.api.get_bot_config("ANNOUNCEMENT_CHANNEL_ID")
                    if channel_id_str and plugin.app:
                        try:
                            await plugin.app.rest.create_message(
                                int(channel_id_str),
                                content=f"🏆 ¡La partida en **{current_map}** ha terminado!\nEl MVP fue **{mvp_name}** (`{mvp_steam}`). Se le ha otorgado {membership_days} día(s) de VIP gratis."
                            )
                            logger.info(f"[Match Monitor] 📢 Anuncio enviado a Discord (Canal: {channel_id_str}).")
                        except Exception as e:
                            logger.error(f"[Match Monitor] No se pudo enviar el mensaje a Discord: {e}")
                            
        elif not match_ended:
            if plugin.model.active_match_id != f"{match_identifier}_running":
                logger.info(f"[Match Monitor] ⚔️ Nueva partida en curso: {current_map} (ID: {match_identifier})")
            # Si el score baja (nueva partida)
            plugin.model.active_match_id = f"{match_identifier}_running"
            
        # Update Bot Presence
        if plugin.app and plugin.app.is_alive:
            presence_text = format_match_presence(status, match_ended=match_ended)
            await plugin.app.update_presence(
                activity=hikari.Activity(
                    name=presence_text,
                    type=hikari.ActivityType.PLAYING
                )
            )
            
    except Exception as e:
        logger.exception(f"[Match Monitor] Error en la automatización: {e!r}")
        if plugin.app and plugin.app.is_alive:
            try:
                await plugin.app.update_presence(
                    activity=hikari.Activity(
                        name="Mantenimiento / Reiniciando"[:35],
                        type=hikari.ActivityType.PLAYING
                    )
                )
            except Exception:
                pass

# Tarea de monitoreo de ingreso de VIPs
@plugin.include
@tasks.loop(seconds=10)
async def vip_monitor():
    if not plugin.model.api:
        return
        
    try:
        data = await plugin.model.api.get_players()
        players = data.players or []
        
        current_steam_ids = {p.steamId for p in players if p.steamId}
        
        # Detectar nuevos jugadores
        cached_ids = set(plugin.model.players_cache.keys())
        new_ids = current_steam_ids - cached_ids
        
        if not plugin.model.initial_scan_done:
            plugin.model.initial_scan_done = True
            logger.info(f"[VIP Monitor] 🚪 Escaneo inicial completado. {len(current_steam_ids)} jugadores en servidor. Omitiendo saludos.")
        elif len(new_ids) > 5:
            logger.info(f"[VIP Monitor] 🚪 Carga masiva detectada ({len(new_ids)} jugadores). Omitiendo mensajes de bienvenida.")
        else:
            if new_ids:
                logger.info(f"[VIP Monitor] 🚪 {len(new_ids)} jugador(es) nuevo(s) detectado(s). Analizando roles...")
            
            # Procesar nuevos jugadores
            for steam_id in new_ids:
                user_data = await plugin.model.api.get_player_by_steam(steam_id)
                if user_data:
                    welcome_message = getattr(user_data, 'custom_welcome_message', None)
                    active_role = getattr(user_data, 'role', getattr(user_data, 'active_role', None))
                    
                    # Verificar que todavia sea VIP o ADMIN
                    if welcome_message and active_role:
                        now = time.time()
                        last_seen = plugin.model.player_last_seen.get(steam_id, 0)
                        
                        # Fix: Don't re-announce if we saw them less than 5 minutes ago (handles map rotations / quick reconnects)
                        if now - last_seen < VIP_BROADCAST_COOLDOWN_SECONDS:
                            continue
                            
                        target_player = next((p for p in players if p.steamId == steam_id), None)
                        player_name = target_player.name if target_player else "Jugador"
                        
                        formatted_msg = f"El {active_role} {player_name} se conectó: \"{welcome_message}\""
                        logger.info(f"[VIP Monitor] ✨ ¡VIP ingresó! Enviando mensaje: '{formatted_msg}'")
                        
                        # Enviar broadcast
                        await plugin.model.api.broadcast(formatted_msg)
                        
                        # Fix: Delay between broadcasts to avoid RCON bursts that overwrite previous messages
                        await asyncio.sleep(VIP_BROADCAST_DELAY_SECONDS)
        
        # Detectar gastos (decremento de cash) y actualizar last_seen
        now = time.time()
        for p in players:
            sid = p.steamId
            if not sid:
                continue
            plugin.model.player_last_seen[sid] = now
            
            current_cash = p.cash or 0
            if sid in plugin.model.players_cache:
                prev_cash = plugin.model.players_cache[sid]
                if current_cash < prev_cash:
                    spent = prev_cash - current_cash
                    logger.info(f"[Economy Monitor] 💸 El jugador {p.name} ({sid}) gastó ${spent}. Cash actual: ${current_cash}")
                    # TODO: Registrar 'spent' en stats_history
            plugin.model.players_cache[sid] = current_cash
            
        # Limpiar desconectados y podar entradas antiguas de last_seen para evitar fugas de memoria
        disconnected = cached_ids - current_steam_ids
        for sid in disconnected:
            if sid in plugin.model.players_cache:
                logger.debug(f"[VIP Monitor] 🔌 Jugador {sid} desconectado. Limpiando caché.")
                del plugin.model.players_cache[sid]

        cutoff = now - PLAYER_LAST_SEEN_PRUNE_SECONDS
        stale_sids = [sid for sid, seen_time in plugin.model.player_last_seen.items() if seen_time < cutoff]
        for sid in stale_sids:
            del plugin.model.player_last_seen[sid]
                
    except Exception as e:
        logger.exception(f"[VIP Monitor] Error en la automatización: {e!r}")

async def execute_membership_sync(
    app: hikari.GatewayBot,
    model: Model,
    target_guild_id: int | None = None
) -> dict[str, Any]:
    """
    Ejecuta la sincronización completa de membresías:
    1. Llama a API sync_memberships() (desactiva expiradas e inyecta slots en RCON).
    2. Reconcilia roles de Discord (añade activos, remueve expirados, respeta whitelist).
    Retorna métricas del proceso.
    """
    if not model.api or not app:
        return {"success": False, "error": "API o Bot no inicializado"}

    res = await model.api.sync_memberships()
    sync_data = res.get("sync_data", [])
    role_maps = res.get("role_maps", {})
    managed_special_roles = res.get("managed_special_roles", [])
    expired_count = res.get("expired_count", 0)
    active_rcon_slots = res.get("active_rcon_slots", 0)

    configs = await model.api.get_bot_configs()
    wl_str = configs.get("SYNC_WHITELIST", "")
    whitelist = set(wl_str.split(",")) if wl_str else set()

    all_managed_roles = {int(r) for r in set(role_maps.values()).union(set(managed_special_roles)) if str(r).isdigit()}

    # El rol de link nunca debe ser removido por la sincronización de membresías como expirado
    link_role_str = configs.get("LINK_ROLE_ID")
    if link_role_str and link_role_str.isdigit():
        all_managed_roles.discard(int(link_role_str))

    stats: dict[str, Any] = {
        "success": True,
        "expired_count": expired_count,
        "active_rcon_slots": active_rcon_slots,
        "users_checked": 0,
        "roles_added": 0,
        "roles_removed": 0,
        "whitelist_skipped": 0,
    }

    has_managed_roles = bool(all_managed_roles) or bool(link_role_str and link_role_str.isdigit())
    if not has_managed_roles:
        return stats

    relevant_roles = set(all_managed_roles)
    if link_role_str and link_role_str.isdigit():
        relevant_roles.add(int(link_role_str))

    if target_guild_id:
        target_guilds = [target_guild_id]
    else:
        target_guilds = []
        for g_id in app.cache.get_guilds_view():
            roles_view = app.cache.get_roles_view_for_guild(g_id)
            if roles_view and not any(r in roles_view for r in relevant_roles):
                continue
            target_guilds.append(g_id)

    if not target_guilds:
        return stats

    for user_data in sync_data:
        discord_id_str = user_data.get('discord_id')

        if not discord_id_str:
            continue

        if discord_id_str in whitelist:
            stats["whitelist_skipped"] += 1
            logger.info(f"[Sync] Usuario {discord_id_str} está en Whitelist, saltando sincronización.")
            continue

        active_memberships = user_data.get('active_memberships', [])
        special_roles = user_data.get('special_roles', [])
        discord_id = int(discord_id_str)
        stats["users_checked"] += 1

        roles_to_have = []
        for m_type in sorted(active_memberships):
            r_id = role_maps.get(m_type)
            if r_id:
                roles_to_have.append(int(r_id))

        for sr in sorted(special_roles):
            roles_to_have.append(int(sr))

        if link_role_str and link_role_str.isdigit():
            roles_to_have.append(int(link_role_str))

        for guild_id in target_guilds:
            try:
                await asyncio.sleep(0.2) # Rate limit safety
                member = app.cache.get_member(guild_id, discord_id)
                if not member:
                    member = await app.rest.fetch_member(guild_id, discord_id)

                if member:
                    current_roles = set(member.role_ids)

                    # 1. Remove managed roles they shouldn't have (VIP / Special)
                    for r_id in sorted(all_managed_roles):
                        if r_id in current_roles and r_id not in roles_to_have:
                            await app.rest.remove_role_from_member(guild_id, discord_id, r_id)
                            stats["roles_removed"] += 1
                            logger.info(f"[Sync] Rol {r_id} removido de {discord_id} (Expiró/Revocado)")

                    # 3. Add roles they should have
                    for r_id in sorted(roles_to_have):
                        if r_id not in current_roles:
                            await app.rest.add_role_to_member(guild_id, discord_id, r_id)
                            stats["roles_added"] += 1
                            logger.info(f"[Sync] Rol {r_id} añadido a {discord_id} (Sincronizado)")

            except hikari.NotFoundError:
                pass
            except Exception as e:
                logger.error(f"[Sync] Error actualizando roles de {discord_id}: {e}")

    return stats

async def sync_single_user_roles(app: Any, model: Any, discord_id: int | str, target_guild_id: int | str | None = None) -> dict[str, Any]:
    """Sincroniza roles de Discord y estado RCON para un único usuario específico (rápido y atómico)."""
    try:
        discord_id_int = int(discord_id)
        discord_id_str = str(discord_id)

        bot_api = getattr(model, "api", None)
        if not bot_api:
            return {"added": 0, "removed": 0, "success": False, "error": "API no disponible"}

        configs = await bot_api.get_bot_configs()
        if not isinstance(configs, dict):
            configs = {}

        wl_str = configs.get("SYNC_WHITELIST", "")
        whitelist = set(wl_str.split(",")) if wl_str else set()
        if discord_id_str in whitelist:
            logger.info(f"[Sync Single] Usuario {discord_id_str} está en Whitelist, saltando sincronización.")
            return {"added": 0, "removed": 0, "success": True, "whitelist_skipped": True}

        res = await bot_api.sync_memberships()
        if not isinstance(res, dict):
            res = {}

        role_maps = res.get("role_maps", {}) if isinstance(res.get("role_maps"), dict) else {}
        managed_special_roles = res.get("managed_special_roles", []) if isinstance(res.get("managed_special_roles"), list) else []

        all_managed_roles = {int(r) for r in set(role_maps.values()).union(set(managed_special_roles)) if str(r).isdigit()}

        link_role_str = configs.get("LINK_ROLE_ID")
        link_role_id = int(link_role_str) if (link_role_str and link_role_str.isdigit()) else None
        if link_role_id:
            all_managed_roles.add(link_role_id)

        sync_data = res.get("sync_data", []) if isinstance(res.get("sync_data"), list) else []
        user_data = next((u for u in sync_data if isinstance(u, dict) and str(u.get("discord_id")) == discord_id_str), None)

        roles_to_have: set[int] = set()
        if user_data:
            active_memberships = user_data.get('active_memberships', []) or []
            special_roles = user_data.get('special_roles', []) or []

            for m_type in active_memberships:
                r_id = role_maps.get(m_type)
                if r_id and str(r_id).isdigit():
                    roles_to_have.add(int(r_id))
            for sr in special_roles:
                if str(sr).isdigit():
                    roles_to_have.add(int(sr))

            if link_role_id:
                roles_to_have.add(link_role_id)

        if target_guild_id:
            try:
                target_guilds = [int(target_guild_id)]
            except Exception:
                target_guilds = []
        else:
            try:
                cache_guilds = app.cache.get_guilds_view()
                target_guilds = [int(g) for g in cache_guilds if str(g).isdigit()]
            except Exception:
                target_guilds = []

        added = 0
        removed = 0

        for guild_id in target_guilds:
            try:
                await asyncio.sleep(0.1) # Rate limit safety for single sync
                member = None
                if hasattr(app, "cache") and hasattr(app.cache, "get_member"):
                    member = app.cache.get_member(guild_id, discord_id_int)
                if not member and hasattr(app, "rest") and hasattr(app.rest, "fetch_member"):
                    member = await app.rest.fetch_member(guild_id, discord_id_int)

                if member:
                    current_roles = set(getattr(member, "role_ids", []))

                    for r_id in sorted(all_managed_roles):
                        if r_id in current_roles and r_id not in roles_to_have:
                            try:
                                await app.rest.remove_role_from_member(guild_id, discord_id_int, r_id)
                                removed += 1
                                logger.info(f"[Sync Single] Rol {r_id} removido de {discord_id_str}")
                            except Exception as ex:
                                logger.warning(f"[Sync Single] No se pudo remover rol {r_id} a {discord_id_str}: {ex}")

                    for r_id in sorted(roles_to_have):
                        if r_id not in current_roles:
                            try:
                                await app.rest.add_role_to_member(guild_id, discord_id_int, r_id)
                                added += 1
                                logger.info(f"[Sync Single] Rol {r_id} asignado a {discord_id_str}")
                            except Exception as ex:
                                logger.warning(f"[Sync Single] No se pudo añadir rol {r_id} a {discord_id_str}: {ex}")
            except (hikari.NotFoundError, hikari.ForbiddenError):
                pass
            except Exception as e:
                logger.error(f"[Sync Single] Error actualizando roles de {discord_id_str} en guild {guild_id}: {e}")

        return {"added": added, "removed": removed, "success": True}
    except Exception as e:
        logger.error(f"[Sync Single] Error general: {e}")
        return {"success": False, "error": str(e)}


# Tarea de sincronización de membresías y roles
@plugin.include
@tasks.loop(minutes=5)
async def membership_monitor():
    if not plugin.model.api or not plugin.app:
        return
        
    try:
        await execute_membership_sync(plugin.app, plugin.model)
    except Exception as e:
        logger.exception(f"[Sync] Error en la automatización: {e!r}")

@plugin.include
@tasks.loop(seconds=5)
async def hacker_monitor_task():
    if not plugin.model.api or not plugin.app or not getattr(plugin.model, "hacker_monitors", None):
        return

    monitors_to_remove = []
    
    try:
        status = await plugin.model.api.get_players()
        players = status.players or []
        
        for steam_id, monitor_data in list(plugin.model.hacker_monitors.items()):
            target_player = next((p for p in players if p.steamId == steam_id), None)
            
            if not target_player:
                embed = hikari.Embed(
                    title="🛑 Monitoreo Finalizado",
                    description=f"El jugador {monitor_data['player_name']} ha abandonado la partida.",
                    color=COLOR_GRAY
                )
                try:
                    await plugin.app.rest.edit_message(monitor_data['channel_id'], monitor_data['message_id'], embed=embed, components=[])
                except Exception:
                    pass
                monitors_to_remove.append(steam_id)
                continue
                
            current_kills = target_player.kills or 0
            start_kills = monitor_data["start_kills"]
            start_time = monitor_data["start_time"]
            
            elapsed_seconds = time.time() - start_time
            elapsed_minutes = elapsed_seconds / 60.0
            
            # Avoid division by very small numbers initially
            elapsed_minutes = max(elapsed_minutes, 0.05)
                
            kpm = (current_kills - start_kills) / elapsed_minutes
            
            # Update last kills for potential reference
            monitor_data["last_kills"] = current_kills
            
            color = COLOR_BLUE
            alert_msg = "Calculando métricas en tiempo real..."
            
            # If KPM > 1.0 and we've measured for at least 1 minute (60s)
            if elapsed_seconds > 60:
                if kpm > 1.0:
                    color = COLOR_RED
                    alert_msg = "⚠️ **¡ALERTA!** KPM anormalmente alto (>1.0). Posible hack o vehículo pesado."
                else:
                    color = COLOR_GREEN
                    alert_msg = "Monitoreo en curso. Tasa de KPM dentro de rangos normales."
                
            embed = hikari.Embed(
                title=f"🕵️ Monitoreando a: {target_player.name}",
                description=alert_msg,
                color=color
            )
            embed.add_field(name="Kills (Inicial -> Actual)", value=f"{start_kills} -> **{current_kills}**", inline=True)
            embed.add_field(name="Tiempo (Minutos)", value=f"{elapsed_minutes:.2f}m", inline=True)
            embed.add_field(name="KPM (Kills/Min)", value=f"**{kpm:.2f}**", inline=True)
            
            try:
                await plugin.app.rest.edit_message(
                    monitor_data['channel_id'], 
                    monitor_data['message_id'], 
                    embed=embed
                )
            except hikari.NotFoundError:
                monitors_to_remove.append(steam_id) # Message was deleted
            except Exception as e:
                logger.error(f"[Hacker Monitor] Error updating message: {e}")
                
    except Exception as e:
        logger.error(f"[Hacker Monitor] Error in loop: {e}")
        
    for sid in monitors_to_remove:
        if sid in plugin.model.hacker_monitors:
            del plugin.model.hacker_monitors[sid]

@plugin.include
@tasks.loop(seconds=30)
async def match_announcer_task():
    if not plugin.model.api or not plugin.app:
        return
        
    try:
        # Get configured channel
        configs = await plugin.model.api.get_bot_configs()
        channel_id_str = configs.get("MATCH_ANNOUNCE_CHANNEL_ID")
        if not channel_id_str:
            return
            
        channel_id = int(channel_id_str)
        
        # Get latest match
        match = await plugin.model.api.get_latest_match()
        if not match or not match.get("end_time"):
            return
            
        # Check if already announced
        last_announced = configs.get("LAST_ANNOUNCED_MATCH_ID")
        if last_announced == match["id"]:
            return
            
        # We have a new finished match to announce!
        
        # Find winning team
        winning_team = next((ts for ts in match.get("team_stats", []) if ts["team_id"] == match.get("winning_team_id")), None)
        winning_team_name = winning_team["team_name"] if winning_team else "Empate/Desconocido"
        winning_score = winning_team["score"] if winning_team else 0
        
        # Find MVP (most kills)
        players = match.get("player_stats", [])
        mvp = max(players, key=lambda x: x.get("kills", 0), default=None) if players else None
        
        # Find Top Earner
        top_earner = max(players, key=lambda x: x.get("cash_earned", 0), default=None) if players else None
        
        # Get Steam names for MVP and Earner
        steam_ids_to_fetch = []
        if mvp: steam_ids_to_fetch.append(mvp["steam_id"])
        if top_earner: steam_ids_to_fetch.append(top_earner["steam_id"])
        
        steam_names = {}
        if steam_ids_to_fetch:
            steam_profiles = await plugin.model.api.get_steam_players_batch(steam_ids_to_fetch)
            for sid, profile in steam_profiles.items():
                if profile and "personaname" in profile:
                    steam_names[sid] = profile["personaname"]
                    
        mvp_name = steam_names.get(mvp["steam_id"], "Desconocido") if mvp else "N/A"
        top_earner_name = steam_names.get(top_earner["steam_id"], "Desconocido") if top_earner else "N/A"
        
        # Build Embed
        embed = hikari.Embed(
            title="🏁 ¡Partida Finalizada!",
            description=f"La batalla en **{match.get('map', 'Desconocido')}** ha terminado.",
            color=COLOR_GOLD
        )
        
        embed.add_field(name="🏆 Ganador", value=f"**{winning_team_name}** con {winning_score} puntos", inline=False)
        
        if mvp:
            embed.add_field(name="🥇 MVP de la Partida", value=f"**{mvp_name}** ({mvp.get('kills', 0)} Kills / {mvp.get('deaths', 0)} Deaths)", inline=True)
            
        if top_earner:
            embed.add_field(name="💰 Mayor Recaudación", value=f"**{top_earner_name}** (${top_earner.get('cash_earned', 0)})", inline=True)
            
        embed.set_footer(text=f"Match ID: {match['id'][:8]}")
        
        # Send
        await plugin.app.rest.create_message(channel_id, embed=embed)
        
        # Mark as announced
        await plugin.model.api.set_bot_config("LAST_ANNOUNCED_MATCH_ID", match["id"])
        logger.info(f"[Match Announcer] Anunciada partida {match['id']}")
        
    except Exception as e:
        logger.exception(f"[Match Announcer] Error: {e!r}")


@plugin.include
@tasks.loop(hours=2)
async def expiration_notifier_task():
    if not plugin.model.api or not plugin.app:
        return
        
    try:
        data = await plugin.model.api.get_expiring_memberships()
        if not data:
            return
            
        expiring_3d = data.get("expiring_3d", [])
        expiring_24h = data.get("expiring_24h", [])
        
        for mem in expiring_3d:
            discord_id = mem.get("discord_id")
            if discord_id and str(discord_id).isdigit():
                try:
                    user = await plugin.app.rest.fetch_user(int(discord_id))
                    await user.send(content=f"⚠️ **Aviso de Vencimiento VIP**\n\nHola, te avisamos que tu membresía VIP ({mem.get('type')}) está por vencer en **3 días** o menos. ¡Aprovecha el tiempo y considera renovarla si lo deseas!")
                    await plugin.model.api.mark_membership_notified(mem.get("id"), "3d")
                    logger.info(f"[Expiration Notifier] Aviso de 3 días enviado a {discord_id}")
                    await asyncio.sleep(1) # rate limit
                except hikari.ForbiddenError:
                    logger.warning(f"[Expiration Notifier] No se pudo enviar DM a {discord_id} (DMs cerrados)")
                    await plugin.model.api.mark_membership_notified(mem.get("id"), "3d") # mark anyway so we don't spam errors
                except Exception as e:
                    logger.error(f"[Expiration Notifier] Error al avisar 3d a {discord_id}: {e}")
                    
        for mem in expiring_24h:
            discord_id = mem.get("discord_id")
            if discord_id and str(discord_id).isdigit():
                try:
                    user = await plugin.app.rest.fetch_user(int(discord_id))
                    await user.send(content=f"🚨 **ALERTA: Vencimiento VIP Inminente**\n\nHola, tu membresía VIP ({mem.get('type')}) vencerá en **menos de 24 horas**. ¡Esperamos que hayas disfrutado tus beneficios!")
                    await plugin.model.api.mark_membership_notified(mem.get("id"), "24h")
                    logger.info(f"[Expiration Notifier] Aviso de 24 horas enviado a {discord_id}")
                    await asyncio.sleep(1) # rate limit
                except hikari.ForbiddenError:
                    logger.warning(f"[Expiration Notifier] No se pudo enviar DM a {discord_id} (DMs cerrados)")
                    await plugin.model.api.mark_membership_notified(mem.get("id"), "24h")
                except Exception as e:
                    logger.error(f"[Expiration Notifier] Error al avisar 24h a {discord_id}: {e}")
                    
    except Exception as e:
        logger.exception(f"[Expiration Notifier] Error general: {e!r}")
