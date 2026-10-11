"""Script para clonar todos los datos de PRODUCCIÓN (PROD) a un entorno de destino (DEV o LOCAL).

Mantiene íntegras las relaciones, adapta los esquemas a la versión HEAD (DDD roles,
is_booster, payment_source, multi-rcon, membership_types) y preserva todos los
jugadores vinculados, membresías activas y estadísticas.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("clone_prod")


async def fetch_table_rows(engine, table_name: str) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        res = await conn.execute(text(f"SELECT * FROM {table_name};"))
        columns = res.keys()
        rows = [dict(zip(columns, row)) for row in res.fetchall()]
        logger.info(f"Leídos {len(rows)} registros de '{table_name}' en PROD")
        return rows


async def clone_data(target_name: str, target_url: str, prod_url: str):
    logger.info(f"=== INICIANDO CLONACIÓN DE PROD HACIA '{target_name.upper()}' ===")
    logger.info(f"Target URL: {target_url.split('@')[-1]}")

    prod_engine = create_async_engine(prod_url)
    target_engine = create_async_engine(target_url)

    # 1. Leer datos de PROD
    teams = await fetch_table_rows(prod_engine, "teams")
    roles_raw = await fetch_table_rows(prod_engine, "roles")
    players = await fetch_table_rows(prod_engine, "players")
    player_roles = await fetch_table_rows(prod_engine, "player_roles")
    memberships_raw = await fetch_table_rows(prod_engine, "memberships")
    bot_config = await fetch_table_rows(prod_engine, "bot_config")
    membership_types = await fetch_table_rows(prod_engine, "membership_types")
    try:
        membership_type_configs = await fetch_table_rows(prod_engine, "membership_type_configs")
    except Exception:
        membership_type_configs = []
    matches = await fetch_table_rows(prod_engine, "matches")
    match_team_stats = await fetch_table_rows(prod_engine, "match_team_stats")
    match_player_stats = await fetch_table_rows(prod_engine, "match_player_stats")
    player_sessions = await fetch_table_rows(prod_engine, "player_sessions")
    rcon_servers = await fetch_table_rows(prod_engine, "rcon_servers")
    try:
        payment_records = await fetch_table_rows(prod_engine, "payment_records")
    except Exception:
        payment_records = []

    await prod_engine.dispose()

    # 2. Adaptar Roles al modelo DDD
    roles_adapted = []
    for r in roles_raw:
        roles_adapted.append({
            "id": r["id"],
            "name": r.get("name") or f"Rol #{r['id']}",
            "code": r.get("code") or f"ROLE_{r['id']}",
            "discord_role_id": r.get("discord_role_id"),
            "role_type": r.get("role_type", "SPECIAL")
        })

    # 3. Adaptar Membresías
    memberships_adapted = []
    for m in memberships_raw:
        m_copy = dict(m)
        if "is_booster" not in m_copy or m_copy["is_booster"] is None:
            m_copy["is_booster"] = False
        if "payment_source" not in m_copy or not m_copy["payment_source"]:
            m_copy["payment_source"] = "MANUAL"
        if "server_id" not in m_copy:
            m_copy["server_id"] = None
        memberships_adapted.append(m_copy)

    # 4. Insertar en Target dentro de una sola transacción
    async with target_engine.begin() as conn:
        # Preservar in_game_name, avatar_url y configs locales si ya existían
        target_player_info = {}
        try:
            tp_res = await conn.execute(text("SELECT steam_id, in_game_name, avatar_url FROM players WHERE in_game_name IS NOT NULL OR avatar_url IS NOT NULL;"))
            for sid, ign, av in tp_res.fetchall():
                target_player_info[sid] = (ign, av)
        except Exception:
            pass

        target_custom_configs = {}
        try:
            t_configs = await conn.execute(text("SELECT config_key, config_value FROM bot_config;"))
            for k, v in t_configs.fetchall():
                if k in ("LINK_ROLE_ID", "ANNOUNCEMENT_CHANNEL_ID"):
                    target_custom_configs[k] = v
        except Exception:
            pass

        logger.info(f"Limpiando tablas existentes en {target_name}...")
        tables_to_truncate = [
            "match_player_stats", "match_team_stats", "player_sessions", "matches",
            "memberships", "player_roles", "membership_types", "rcon_servers",
            "roles", "players", "teams", "bot_config"
        ]
        for t in tables_to_truncate:
            try:
                await conn.execute(text(f"TRUNCATE TABLE {t} CASCADE;"))
            except Exception:
                pass

        # Insertar Teams
        if teams:
            logger.info(f"Insertando {len(teams)} teams...")
            await conn.execute(text("INSERT INTO teams (id, name, code) VALUES (:id, :name, :code)"), teams)

        # Insertar Roles adaptados
        if roles_adapted:
            logger.info(f"Insertando {len(roles_adapted)} roles adaptados...")
            await conn.execute(text(
                "INSERT INTO roles (id, name, code, discord_role_id, role_type) "
                "VALUES (:id, :name, :code, :discord_role_id, :role_type)"
            ), roles_adapted)
            await conn.execute(text("SELECT setval('roles_id_seq', (SELECT COALESCE(MAX(id), 1) FROM roles));"))

        # Insertar Players
        if players:
            logger.info(f"Insertando {len(players)} players...")
            for p in players:
                sid = p.get("steam_id")
                if sid in target_player_info:
                    cached_ign, cached_av = target_player_info[sid]
                    if not p.get("in_game_name") and cached_ign:
                        p["in_game_name"] = cached_ign
                    if not p.get("avatar_url") and cached_av:
                        p["avatar_url"] = cached_av
            await conn.execute(text(
                "INSERT INTO players (steam_id, discord_id, custom_welcome_message, observations, in_game_name, avatar_url) "
                "VALUES (:steam_id, :discord_id, :custom_welcome_message, :observations, :in_game_name, :avatar_url)"
            ), players)

        # Insertar RCON Servers
        if rcon_servers:
            logger.info(f"Insertando {len(rcon_servers)} rcon_servers...")
            await conn.execute(text(
                "INSERT INTO rcon_servers (id, name, ip, port, password, scheme, is_active, is_default, created_at, updated_at) "
                "VALUES (:id, :name, :ip, :port, :password, :scheme, :is_active, :is_default, :created_at, :updated_at)"
            ), rcon_servers)
            await conn.execute(text("SELECT setval('rcon_servers_id_seq', (SELECT COALESCE(MAX(id), 1) FROM rcon_servers));"))
        else:
            logger.info("Semillando servidor RCON principal por defecto...")
            await conn.execute(text(
                "INSERT INTO rcon_servers (id, name, ip, port, password, scheme, is_active, is_default) "
                "VALUES (1, 'Servidor Principal SAO', '169.155.127.77', 9001, 'dVt2ajQzYqGKnDft', 'http', true, true) "
                "ON CONFLICT (id) DO NOTHING;"
            ))
            await conn.execute(text("SELECT setval('rcon_servers_id_seq', (SELECT COALESCE(MAX(id), 1) FROM rcon_servers));"))

        # Insertar Membership Types de PROD
        if membership_types:
            logger.info(f"Insertando {len(membership_types)} membership_types de PROD...")
            await conn.execute(text(
                "INSERT INTO membership_types ("
                "   id, code, name, description, price_usd, billing_type, default_days, max_quota, "
                "   role_id, server_id, is_active, created_at, updated_at"
                ") VALUES ("
                "   :id, :code, :name, :description, :price_usd, :billing_type, :default_days, :max_quota, "
                "   :role_id, :server_id, :is_active, :created_at, :updated_at"
                ")"
            ), membership_types)
            await conn.execute(text("SELECT setval('membership_types_id_seq', (SELECT COALESCE(MAX(id), 1) FROM membership_types));"))

        # Insertar Payment Records de PROD
        if payment_records:
            logger.info(f"Insertando {len(payment_records)} payment_records...")
            await conn.execute(text(
                "INSERT INTO payment_records ("
                "   id, transaction_id, event_type, steam_id, discord_id, package_id, package_name, "
                "   amount, currency, status, raw_payload, created_at"
                ") VALUES ("
                "   :id, :transaction_id, :event_type, :steam_id, :discord_id, :package_id, :package_name, "
                "   :amount, :currency, :status, :raw_payload, :created_at"
                ")"
            ), payment_records)
            await conn.execute(text("SELECT setval('payment_records_id_seq', (SELECT COALESCE(MAX(id), 1) FROM payment_records));"))

        # Insertar Player Roles
        if player_roles:
            logger.info(f"Insertando {len(player_roles)} player_roles...")
            await conn.execute(text("INSERT INTO player_roles (steam_id, role_id) VALUES (:steam_id, :role_id)"), player_roles)

        # Insertar Memberships adaptadas
        if memberships_adapted:
            logger.info(f"Insertando {len(memberships_adapted)} memberships...")
            # En base de datos la columna es 'type', 'start_date', 'end_date', 'role_granted_id'
            await conn.execute(text(
                "INSERT INTO memberships ("
                "   id, steam_id, type, start_date, end_date, is_active, role_granted_id, "
                "   rcon_sync_status, is_booster, server_id, payment_source"
                ") VALUES ("
                "   :id, :steam_id, :type, :start_date, :end_date, :is_active, :role_granted_id, "
                "   :rcon_sync_status, :is_booster, :server_id, :payment_source"
                ")"
            ), memberships_adapted)
            await conn.execute(text("SELECT setval('memberships_id_seq', (SELECT COALESCE(MAX(id), 1) FROM memberships));"))

