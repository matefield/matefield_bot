#!/usr/bin/env python3
"""
tools/sim_local_suite.py
Exhaustive runtime simulation and bug-hunting test suite for Matefield Bot & API.
Executes against the local Docker Compose environment (PostgreSQL + Mock RCON + FastAPI).
"""

import asyncio
import os
import sys
import logging
from typing import Dict, Any

# Ensure proper PYTHONPATH
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("packages/wardogs_schemas/src"))
sys.path.insert(0, os.path.abspath("packages/wardogs_config/src"))

import httpx
from apps.discord_bot.src.api_client import APIClient
from wardogs_schemas.steam_token import create_steam_link_token
from wardogs_config import BOT_SETTINGS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sim_suite")

BASE_URL = BOT_SETTINGS.API_BASE_URL
API_KEY = BOT_SETTINGS.API_KEY

class SimulationRunner:
    def __init__(self):
        self.client = APIClient(BASE_URL, API_KEY)
        self.http = httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)
        self.passed = 0
        self.failed = 0
        self.test_discord_id = "999888777666555"
        self.test_steam_id = None
        self.cleanup_tasks = []

    def assert_true(self, condition: bool, message: str):
        if condition:
            self.passed += 1
            logger.info(f"  [PASS] {message}")
        else:
            self.failed += 1
            logger.error(f"  [FAIL] {message}")
            raise AssertionError(message)

    async def run_all(self):
        logger.info("==================================================================")
        logger.info("🚀 INICIANDO BATERÍA DE SIMULACIONES LOCALES (DOCKER COMPOSE STACK)")
        logger.info(f"Target API: {BASE_URL} | API Key: {API_KEY}")
        logger.info("==================================================================")

        try:
            await self.test_health_and_rcon()
            await self.test_db_player_sampling()
            await self.test_steam_auth_flow()
            await self.test_account_linking_rules()
            await self.test_rewards_catalog_and_seeding_config()
            await self.test_rewards_linking_enforcement()
            await self.test_rewards_points_and_boundary_checks()
            await self.test_rewards_claim_automatic_vip()
            await self.test_rewards_claim_manual_ticket_and_refund()
            await self.test_sync_engine_and_roles()
        finally:
            await self.cleanup()
            await self.client.close()
            await self.http.aclose()

        logger.info("==================================================================")
        logger.info(f"🏁 RESULTADO DE SIMULACIÓN: {self.passed} PASADAS, {self.failed} FALLIDAS")
        logger.info("==================================================================")
        if self.failed > 0:
            sys.exit(1)

    async def test_health_and_rcon(self):
        logger.info("\n--- 1. Verificación de Estado y Servidor RCON Mock ---")
        status = await self.client.get_status()
        self.assert_true(status is not None, "Endpoint /api/v1/status responde correctamente")
        cur_p = status.players.current if status.players else 0
        self.assert_true(isinstance(cur_p, int), f"Jugadores en línea detectados: {cur_p}")

        players_resp = await self.client.get_players()
        self.assert_true(players_resp is not None, "Endpoint /api/v1/players responde correctamente")
        factions = status.factionScores or []
        logger.info(f"  Info de partida: Mapa '{status.map}', Facciones detectadas: {len(factions)}")

    async def test_db_player_sampling(self):
        logger.info("\n--- 2. Muestreo de Jugadores Reales en Base de Datos Local ---")
        all_players = await self.client.get_paginated_players(page=1, limit=5, linked="all")
        self.assert_true(all_players.get("total", 0) > 0, f"Total de jugadores en DB: {all_players.get('total')}")

        unlinked = await self.client.get_paginated_players(page=1, limit=5, linked="unlinked")
        unlinked_list = unlinked.get("players", [])
        self.assert_true(len(unlinked_list) > 0, f"Jugadores sin vincular disponibles: {len(unlinked_list)}")
        
        # Pick a real unlinked player for our simulation tests, and another to test unlinked rejection
        candidate = unlinked_list[0]
        self.test_steam_id = candidate["steam_id"]
        self.unlinked_steam_id = unlinked_list[1]["steam_id"] if len(unlinked_list) > 1 else "00000000000000000"
        logger.info(f"  Jugador de prueba seleccionado de DB local: SteamID={self.test_steam_id} ({candidate.get('name')})")
        logger.info(f"  Jugador no vinculado para pruebas de restricción: SteamID={self.unlinked_steam_id}")

    async def test_steam_auth_flow(self):
        logger.info("\n--- 3. Flujo de Autenticación Steam OpenID y Manejo de Errores ---")
        # A. Token inválido/expirado en /login
        resp_bad = await self.http.get("/api/v1/auth/steam/login?token=invalid_token_123")
        self.assert_true(resp_bad.status_code == 400, "Token inválido en /login retorna HTTP 400 con HTML amigable")
        self.assert_true("Enlace Expirado o Inválido" in resp_bad.text, "Página de error contiene mensaje amigable")

        # B. Token válido en /login -> redirect a Steam
        valid_token = create_steam_link_token(self.test_discord_id, API_KEY, expires_in=600)
        resp_login = await self.http.get(f"/api/v1/auth/steam/login?token={valid_token}", follow_redirects=False)
        self.assert_true(resp_login.status_code == 303, "Token válido en /login retorna HTTP 303 See Other")
        self.assert_true("steamcommunity.com/openid/login" in resp_login.headers.get("location", ""), "Redirige a Valve OpenID")

        # C. Callback con modo cancelado (cancel login en Steam)
        cancel_params = {"token": valid_token, "openid.mode": "cancel"}
        resp_cancel = await self.http.get("/api/v1/auth/steam/callback", params=cancel_params)
        self.assert_true(resp_cancel.status_code == 400, "Modo cancelado en callback retorna HTTP 400")
        self.assert_true("Autenticación Cancelada" in resp_cancel.text, "Mensaje de cancelación detectado")

    async def test_account_linking_rules(self):
        logger.info("\n--- 4. Reglas de Vinculación, Fallback y Desvinculación ---")
        # Asegurar que el jugador está desvinculado antes de comenzar
        try:
            await self.client.unlink_account(self.test_discord_id)
        except Exception:
            pass

        # Vincular cuenta
        assert self.test_steam_id is not None
        await self.client.link_account(self.test_discord_id, self.test_steam_id)
        self.cleanup_tasks.append(lambda: self.client.unlink_account(self.test_discord_id))

        # Verificar consulta por Discord ID
        p_by_dc = await self.client.get_player_by_discord(self.test_discord_id)
        self.assert_true(p_by_dc is not None and p_by_dc.steam_id == self.test_steam_id, "get_player_by_discord retorna el SteamID vinculado")

        # Intentar vincular la misma cuenta de Discord a otro SteamID distinto -> debe fallar con 400
        duplicate_prevented = False
        try:
            await self.client.link_account(self.test_discord_id, "76561198000000999")
        except Exception as e:
            if "ya está vinculada" in str(e) or "400" in str(e):
                duplicate_prevented = True
        self.assert_true(duplicate_prevented, "Prevención de doble vinculación de cuenta de Discord activa")

    async def test_rewards_catalog_and_seeding_config(self):
        logger.info("\n--- 5. Catálogo de Recompensas y Configuración de Seeding ---")
        catalog = await self.client.get_rewards_catalog()
        self.assert_true(len(catalog) >= 2, f"Catálogo contiene {len(catalog)} recompensas registradas")
        
        # Verificar ordenamiento por puntos ascendente
        costs = [item.cost_points for item in catalog]
        self.assert_true(costs == sorted(costs), "Catálogo ordenado correctamente por costo de puntos ascendente")

        # Verificar configuración de seeding
        await self.client.set_bot_config("SEEDING_MIN_PLAYERS", "25")
        await self.client.set_bot_config("SEEDING_MINUTES_PER_POINT", "30")
        configs = await self.client.get_bot_configs()
        self.assert_true(configs.get("SEEDING_MIN_PLAYERS") == "25", "SEEDING_MIN_PLAYERS configurado en 25")
        self.assert_true(configs.get("SEEDING_MINUTES_PER_POINT") == "30", "SEEDING_MINUTES_PER_POINT configurado en 30")

    async def test_rewards_linking_enforcement(self):
        logger.info("\n--- 6. Aislamiento y Obligatoriedad de Cuenta Vinculada en Recompensas ---")
        # Consultar balance con un SteamID NO vinculado
        unlinked_error = False
        try:
            await self.client.get_player_rewards_balance(self.unlinked_steam_id)
        except Exception as e:
            if "no tiene su cuenta" in str(e) or "vincul" in str(e) or "400" in str(e):
                unlinked_error = True
        self.assert_true(unlinked_error, "get_player_rewards_balance rechaza con HTTP 400 a jugadores no vinculados")

        # Intentar canje con cuenta no vinculada
        unlinked_claim_err = False
        try:
            await self.client.claim_reward("999999999999999999", "VIP_EXPRESS")
        except Exception as e:
            if "404" in str(e) or "vincul" in str(e) or "no encontrado" in str(e):
                unlinked_claim_err = True
        self.assert_true(unlinked_claim_err, "claim_reward rechaza canjes de usuarios sin cuenta vinculada")

    async def test_rewards_points_and_boundary_checks(self):
        logger.info("\n--- 7. Ajuste de Puntos y Validación de Límites (Boundaries) ---")
        balance = await self.client.get_player_rewards_balance(self.test_discord_id)
        initial_points = balance.reward_points

        # Añadir 250 puntos
        adj_resp = await self.client.give_reward_points(self.test_discord_id, 250, reason="Bono de simulación")
        self.assert_true(adj_resp.get("new_balance") == initial_points + 250, "Puntos añadidos correctamente (+250)")

        # Intentar restar más de lo que tiene -> debe rechazar sin saldo negativo
        negative_prevented = False
        try:
            await self.client.give_reward_points(self.test_discord_id, -10000, reason="Sobregiro")
        except Exception as e:
            if "insuficientes" in str(e).lower() or "negativo" in str(e).lower() or "400" in str(e):
                negative_prevented = True
        self.assert_true(negative_prevented, "Prevención de saldo negativo en puntos estricta")

        # Verificar que el balance sigue intacto
        balance_check = await self.client.get_player_rewards_balance(self.test_discord_id)
        self.assert_true(balance_check.reward_points == initial_points + 250, "Balance se mantiene íntegro tras rechazo")

    async def test_rewards_claim_automatic_vip(self):
        logger.info("\n--- 8. Canje Automático de Recompensa (Membresía / VIP) ---")
        # Asegurarse de tener puntos suficientes
        await self.client.give_reward_points(self.test_discord_id, 500, reason="Cargar puntos para VIP")
        
        # Canjear VIP_SEED (cuesta 100 puntos en catálogo por defecto)
        claim_result = await self.client.claim_reward(self.test_discord_id, "VIP_SEED")
        self.assert_true(claim_result.delivery.delivery_type == "AUTOMATIC", "Entrega automática para VIP")
        self.assert_true(claim_result.claim_code is not None, f"Código de canje generado: {claim_result.claim_code}")
        
        # Verificar que se creó la membresía activa en DB
        m_resp = await self.client.get_paginated_memberships(discord_id=self.test_discord_id)
        memberships = m_resp.get("memberships", [])
        has_seed_vip = any(m.get("type") == "VIP_SEED" and m.get("is_active") for m in memberships)
        self.assert_true(has_seed_vip, "Membresía VIP_SEED creada y activa en DB tras el canje")

    async def test_rewards_claim_manual_ticket_and_refund(self):
        logger.info("\n--- 9. Canje Manual con Ticket de Soporte y Reembolso ---")
        # Crear item manual de prueba en catálogo
        await self.client.create_or_update_reward_item(
            code="CUSTOM_TACTICAL_SKIN",
            name="Skin Táctica Exclusiva",
            cost_points=50,
            delivery_type="MANUAL_TICKET",
            reward_type="CUSTOM",
            reward_value="SKIN_TACTICAL_01",
            description="Skin especial entregada por ticket de staff",
            is_active=True
        )

        # Consultar balance antes del canje
        bal_before = (await self.client.get_player_rewards_balance(self.test_discord_id)).reward_points

        # Canjear
        claim_res = await self.client.claim_reward(self.test_discord_id, "CUSTOM_TACTICAL_SKIN")
        claim_code = claim_res.claim_code
        self.assert_true(claim_res.delivery.delivery_type == "MANUAL_TICKET", "Tipo de entrega MANUAL_TICKET detectado")
        self.assert_true(claim_code.startswith("MF-"), f"Formato de código ticket correcto: {claim_code}")

        # Verificar canje con el endpoint de verificación admin
        verified = await self.client.verify_reward_claim(claim_code)
        self.assert_true(verified.get("status") == "PENDING", "Voucher en estado PENDING tras canje")

        # Simular reembolso de puntos por parte del admin
        refund_res = await self.client.refund_reward_claim(claim_code, refunded_by="AdminTester", reason="Cancelado por staff de prueba")
        self.assert_true(refund_res.get("new_status") == "REFUNDED", "Estado actualizado a REFUNDED")
        
        # Verificar que los 50 puntos volvieron a la cuenta del jugador
        bal_after = (await self.client.get_player_rewards_balance(self.test_discord_id)).reward_points
        self.assert_true(bal_after == bal_before, f"Puntos reembolsados correctamente (Antes={bal_before}, Después={bal_after})")

    async def test_sync_engine_and_roles(self):
        logger.info("\n--- 10. Motor de Sincronización Global de Membresías y Roles ---")
        sync_result = await self.client.sync_memberships()
        self.assert_true("sync_data" in sync_result, "sync_memberships devuelve sync_data para Discord Bot")
        self.assert_true("role_maps" in sync_result, "role_maps presente en resultado de sincronización")
        
        sync_players = sync_result.get("sync_data", [])
        self.assert_true(len(sync_players) > 0, f"Jugadores vinculados sincronizados para Discord: {len(sync_players)}")
        
        # Verificar que nuestro jugador de prueba está en sync_data con su membresía VIP_SEED
        test_sync = next((p for p in sync_players if isinstance(p, dict) and p.get("discord_id") == self.test_discord_id), None)
        self.assert_true(test_sync is not None, "Jugador de prueba presente en la data de sincronización de Discord")
        if isinstance(test_sync, dict):
            self.assert_true("VIP_SEED" in test_sync.get("active_memberships", []), "VIP_SEED incluido en membresías activas para Discord")

    async def cleanup(self):
        logger.info("\n--- Limpieza de Datos de Simulación ---")
        for task in reversed(self.cleanup_tasks):
            try:
                await task()
            except Exception as e:
                logger.warning(f"Error en cleanup task: {e}")
        logger.info("  Limpieza completada.")

if __name__ == "__main__":
    runner = SimulationRunner()
    asyncio.run(runner.run_all())
