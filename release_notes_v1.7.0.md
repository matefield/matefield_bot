# Release v1.7.0 🚀 (Notificaciones DM de Vencimiento VIP & Resiliencia en Sincronización)

Esta versión introduce la automatización de avisos privados vía Discord DM para la prevención de expiración de membresías VIP, nuevos endpoints dedicados de monitoreo con persistencia en base de datos, y refuerzos de resiliencia ante desajustes de esquemas en el bot y agregaciones de pelotones.

### 🌟 Nuevas Funcionalidades
- **Notificaciones DM de Vencimiento VIP**:
  - Tarea periódica automatizada (`expiration_notifier_task`) en el bot de Discord ejecutándose cada 2 horas.
  - Avisos proactivos por mensaje directo a los usuarios en dos umbrales clave: **3 días antes** y **menos de 24 horas antes** del vencimiento.
  - Manejo seguro de rate limits de Discord (`asyncio.sleep(1)`) y captura controlada de usuarios con mensajes privados cerrados (`hikari.ForbiddenError`).
- **Endpoints de Monitoreo de Membresías por Vencer**:
  - `GET /api/v1/db/memberships/expiring`: Identifica membresías activas que caen en las ventanas de notificación (3d / 24h) y no han sido notificadas previamente.
  - `POST /api/v1/db/memberships/{id}/mark_notified`: Registra atómicamente la bandera de notificación (`3d` o `24h`) en PostgreSQL.
- **Migración de Base de Datos**:
  - Migración Alembic `0132aeb12a1c_add_notified_columns_to_memberships.py` agregando columnas booleanas `notified_3d` y `notified_24h` a la tabla `memberships`.

### 🐛 Corrección de Bugs y Estabilidad
- **Inyección Defensiva de Identificadores en API Client**:
  - Corrección de `ValidationError` de Pydantic en `get_player_by_steam` y `get_player_by_discord` en `apps/discord_bot/src/api_client.py`. El cliente ahora inyecta defensivamente el identificador recibido cuando el backend responde con esquemas en transición o sin `steam_id`/`discord_id`, evitando caídas en el bucle de `vip_monitor`.
- **Desempaquetado de Tuplas en Estadísticas de Pelotones**:
  - Corrección en `apps/api_rcon/src/modules/v1/services/squads_service.py` (`get_internal_leaderboard`), indexando apropiadamente las tuplas resultantes de SQLAlchemy (`row[0]`, `row[1]`, etc.) para miembros retirados, evitando excepciones de tipo `AttributeError`.
- **Limpieza de Tests y Tipos**:
  - Normalización de instanciaciones de `MembershipType` en `apps/api_rcon/tests/test_role_lifecycle_and_pricing.py` eliminando argumentos duplicados.
  - 100% de la suite de pruebas validada (147 pruebas ejecutadas y pasando con éxito).
