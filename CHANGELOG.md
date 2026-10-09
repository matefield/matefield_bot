# Changelog

Todos los cambios notables en este proyecto serán documentados en este archivo.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y este proyecto se adhiere a [Semantic Versioning (SemVer 2.0.0)](https://semver.org/lang/es/).

---

## [1.6.0] - 2026-10-08

### Añadido
- **Sistema de Pelotones (Squads)**: Soporte completo para crear, gestionar y unirse a escuadrones a través de invitaciones y códigos en Discord (Comandos `/squad`).
- **Sistema de Seeding y Recompensas Automatizadas**: Nuevo motor de recompensas que premia a los jugadores (1 punto por minuto) por poblar el servidor (Seeding) cuando la cantidad de jugadores activos está entre el mínimo y el máximo configurado, detectando estados de "limbo" y penalizando a quienes abandonan el servidor sin jugar antes de que se alcance la cuota.
- **Auditoría de Clonado de Base de Datos**: Creación de herramientas para clonación de bases de datos seguras (`clone_prod_to_env.py`) ignorando esquemas heredados y obsoletos, permitiendo pruebas rigurosas en entornos de staging/dev.

### Cambiado
- **Desvinculación Completa de Tebex**: Limpieza a nivel base de datos, código y documentación (incluyendo remoción de variables de entorno, migraciones antiguas, endpoints y lógicas de reembolsos/disputas) para eliminar Tebex definitivamente.
- **Esquema de Precios de Membresías**: Las membresías permanentes y el rol "VIP Seed" ahora soportan costo `$0` (nullable), quitando restricciones estrictas previas en `price_usd`.

### Corregido
- **Corrupción Aritmética de Puntos**: Se corrigió un error grave en `RewardsService` donde los puntos y logs insertaban literales de expresiones binarias (`BinaryExpression`) en vez de sus valores atómicos calculados, lo que envenenaba la base de datos de PostgreSQL.
- **Gracia de Desconexiones (Seeding Grace Period)**: Se refinó y documentó la constante `SEEDING_FAILURE_GRACE_PERIOD_SECONDS` (90 segundos), consolidando los tiempos de gracia de desconexión sin castigos y limpiando números mágicos hardcodeados.
- **Limpieza de Linting Crítico**: Se solucionaron múltiples excepciones "ciegas" (blind exceptions `try-except-pass`) y problemas en el uso de SQLAlchemy en todo el proyecto.
- **Regresión en Cliente API del Bot**: Se resolvieron incompatibilidades de importación (`wardogs_schemas.v1` vs `dtos`) tras la refactorización del core, asegurando que todos los tests locales pasen al 100%.

---

## [1.5.3] - 2026-10-04
### Añadido
- **UI de Seeding**: Se agregó al comando `/rewards balance` en Discord el tiempo restante estimado ("Siguiente Punto En") calculado dinámicamente usando los minutos residuales de la sesión actual del jugador.

---

## [1.5.2] - 2026-10-04

### Mejorado
- **Estabilidad de Base de Datos (Pool)**: Se limitó el pool de conexiones asíncronas de SQLAlchemy (`pool_size=3`, `max_overflow=2`) para prevenir errores críticos de `TooManyConnectionsError` en entornos con bases de datos compartidas (ej. BisectHosting).
- **Eficiencia en Integración Steam**: Agrupación (batching) de peticiones a la API de Steam durante la sincronización inicial, consolidando hasta 100 consultas individuales en 1 sola llamada para evitar penalizaciones temporales (HTTP 420 Rate Limit).

### Corregido
- **Migraciones Idempotentes**: Se actualizaron los scripts de Alembic (`2c236beea135`) utilizando bloques `DO $$` para evitar caídas catastróficas por `DuplicateObjectError` o violaciones de constraints preexistentes.
- **Docker Context**: Se optimizó `.dockerignore` reduciendo radicalmente el tiempo de "build" bloqueando directorios pesados (`data/`, `backups/`).

---

## [1.5.1] - 2026-10-04

### Corregido
- **Transparencia Financiera (UX/API)**:
  - Se modificó la capa de servicio de la API (`MembershipTypesService`) para que el almacenamiento de dinero en centavos (`int`) sea completamente transparente para los clientes. Ahora la API recibe y entrega flotantes limpios (ej: `6.0`) y maneja la conversión a centavos internamente, garantizando que el usuario final y los administradores de Discord sigan viendo los precios "como dólares comunes".
  - Se eliminaron las opciones de comandos de Discord obsoletas que hacían referencia al antiguo `base_price` (comisiones de Tebex).

---

## [1.5.0] - 2026-10-04

### Agregado
- **Wardogs Config Package**:
  - Centralización de configuraciones de entorno utilizando `pydantic-settings` mediante un paquete independiente local (`packages/wardogs_config`).
  - Integración completa del nuevo paquete de configuración transversal en la API y el Discord Bot para unificar el control de secretos.
- **Auditoría Profunda de Concurrencia y Datos (100-Scenarios)**:
  - Blindaje nativo en PostgreSQL de integridad de datos mediante Constraints (`reward_points >= 0`, `points_spent >= 0`).
  - Cambio en la persistencia financiera de `MembershipType.price_usd` de tipo flotante a Entero (`cents`) para evitar corrupción de coma flotante.
  - Normalización estricta (`UPPER` y `TRIM`) al guardar e ingestar `steam_id` en todos los flujos para rechazar URLs sucias o nicknames.
  - Resolución de vulnerabilidad de 'Dog-piling' (Cache Stampede) en `memberships.py` introduciendo `asyncio.Lock` en la obtención de cachés.
- **Observabilidad en Entornos**:
  - Nuevo módulo de Traza (Patrones Observer y Null Object) atado a `APP_ENV` para inyectar logs visuales de procesos en desarrollo, sin overhead en producción.
- **Migración Segura (Pre-Prod)**:
  - Nueva revisión de Alembic (`2c236beea135`) para sanear silenciosamente Steam IDs rotos, fechas invertidas, transicionar cálculos financieros de $6.00 a 600 centavos, y expandir `bot_config` a tipo TEXT sin colapsos de despliegue.

---

## [1.4.2] - 2026-10-02

### Corregido
- **Demora en Asignación de Rol Verificado**:
  - Se solucionó un problema donde la vinculación vía web fallaba silenciosamente al intentar asignar el rol de Discord de forma instantánea. Esto forzaba al usuario a esperar el ciclo de sincronización en segundo plano (hasta 1 minuto) para recibir el rol.
  - Se agregó un `json={}` explícito en la llamada de `httpx.put` para forzar las cabeceras `Content-Type` y `Content-Length`, satisfaciendo las estrictas reglas de Cloudflare frente a la API de Discord.
  - Se añadieron alertas claras en logs si `api_rcon` arranca sin acceso al token del bot (`DISCORD_TOKEN`), lo cual también inhibiría la inmediatez.

---

## [1.4.1] - 2026-10-01
### Agregado
- **Comando `/roles player_list`**:
  - Nuevo endpoint en `api_rcon` (`GET /api/v1/db/roles/{role_id}/players`) y comando en Discord para listar los jugadores que poseen un rol determinado. Esto facilita la auditoría de roles cruzados y depuración.

### Corregido
- **Cruce de Datos en Asignación de Roles (Script Fix)**:
  - Se identificó y resolvió un problema grave originado en la migración `j6f7a8b9c0d1` (que mapeó tipos de membresías a roles VIP con IDs rígidos y obsoletos en lugar de IDs dinámicos en base al nombre/código en BD).
  - Como el servidor de producción tenía el ID del rol de Administrador/Fundador como `1`, y los IDs hardcodeados (`2`, `3`, `6`) se mezclaron, la migración `k7g8b9c0d1e2` provocó un cruce de datos masivo, otorgando permisos VIP incorrectos (e incluso de Administrador/Fundador) a usuarios con membresías que no correspondían.
  - Se proveyó el script local `fix_roles.py` para ejecutarse en producción, reasignando dinámicamente los roles de membresía en base a los códigos correctos y limpiando el cruce de datos en `player_roles`.

---

## [1.4.0] - 2026-10-01
### Agregado
- **Motor Multi-RCON para Producción**:
  - Soporte completo para múltiples instancias de servidores de juego mediante la tabla `rcon_servers`.
  - Scoping inteligente de sincronización: membresías globales (`server_id = NULL`) se aplican a todos los servidores activos; membresías específicas (`server_id = N`) se sincronizan únicamente con el servidor asignado.
  - Mecanismo de fallback transparente a credenciales de entorno `.env` en caso de no existir servidores registrados en base de datos.
  - Concurrencia controlada con cerraduras asíncronas (`_config_lock`) por servidor para evitar sobreescrituras en `ServerSettings.ini`.
- **Sistema de Puntos y Recompensas**:
  - Nuevo servicio `RewardsService` con acumulación de puntos, redención de beneficios y entrega inmediata de roles verificados.
  - Suite de pruebas de simulación de ejecuciones concurrentes y verificaciones de integridad financiera.
- **Vinculación Segura de Steam desde Discord**:
  - Flujo seguro de vinculación mediante interacción de Discord con tokens firmados de corta duración.
  - Redirección a URLs limpias tras el callback de Steam OpenID evitando exposición de tokens en el historial del navegador.
  - Enlace al canal de soporte oficial (`DISCORD_REQUEST_HELP_CHANNEL_URL`) en pantallas de error contextual.
- **Documentación de Configuración (.env.example)**:
  - Reestructuración integral y documentación exhaustiva de variables de entorno segmentadas en: `API`, `BOT` y `AMBOS` (compartidas).

### Cambiado
- **Control de Tareas en Segundo Plano**:
  - Ciclos de mantenimiento asíncronos en `lifespan` de FastAPI con cancelación limpia y apagado coordinado del pool de conexiones RCON.
- **Configuración Centralizada**:
  - Consolidación de variables en `SecuritySettings` en `src/config/security.py` para prevenir accesos tempranos no inicializados de `os.environ`.

### Corregido
- **Mocks de Pruebas Unitarias**:
  - Corrección en `test_steam_auth.py` para parchear atributos en el singleton `ENVIRONMENT_SETTINGS.SECURITY_SETTINGS` en lugar de variables de entorno volátiles.
  - Compatibilidad de aserciones en `test_interaction_link.py` para códigos de estado de autenticación.
- **Estabilidad de la Suite de Tests**:
  - Cobertura total alcanzada con **100% de pruebas aprobadas** en `api_rcon` y `discord_bot`.

---

## [1.3.0] - 2026-09-26

### Agregado
- **Identidad Visual MATEFIELD en Steam Auth**:
  - Integración de activos oficiales: `BANNER_ICONO_SERVIDOR.png`, `BANNER_FONDO_INVITACION.png` y `steam_icon_black.png`.
  - Estética táctica militar moderna con paleta oscura carbón (`#0f1115`) y verde táctico (`#22c55e`).
  - Montaje de rutas `/static` y `/api/static` en FastAPI para distribución de recursos estáticos.
  - Plantillas interactivas `success_callback.html` y `error_callback.html` con copiado de Steam ID y diagnóstico contextual.
- **Binding de Datos Reales de Usuario**:
  - Token HMAC-SHA256 extendido con metadatos de usuario (`discord_username`, `discord_tag`, `discord_avatar`).
  - Fallback asíncrono hacia la API REST de Discord para resolución de perfiles y avatares.
  - Captura y persistencia de perfiles reales de Steam Community (`personaname`, `avatarfull`).
- **Servicio `AuthPageService`**:
  - Desacoplamiento de la renderización HTML con caché en memoria y resolución de plantillas.

---

## [1.2.0] - 2026-09-24

### Agregado
- **Sincronización RCON y Concurrencia**:
  - Implementación de `_config_lock` (`asyncio.Lock`) en `RCONClient` para serializar modificaciones atómicas en `ServerSettings.ini`.
  - Soporte de slots reservados sin limitación artificial (136+ VIPs garantizados).
  - Detección directa de baneos vía endpoint nativo `GET /v1/bans` del servidor Wardogs.
- **Ciclo de Vida de Suscripciones Tebex**:
  - Manejo del evento `recurring-payment.ended` manteniendo membresía activa hasta agotar la fecha prepagada (`end_time > now`).
  - Revocación estricta reservada para eventos de contracargo o disputas bancarias (`payment.refunded`, `payment.dispute.lost`).
  - Idempotencia en procesamiento de webhooks con registro transaccional en `payment_records`.
- **Modelo de Dominio (DDD)**:
  - Separación estricta entre Membresías (slots temporales en juego) y Roles (identidad en Discord y permisos del sistema).
  - Unificación de jerarquía administrativa bajo la tipología `SYSTEM` (eliminando rol legacy Owner).
  - Asociación de `membership_types` a `roles.id` con soporte de doble precio (`base_price_usd` y `price_usd`).
  - Preservación de roles especiales honoríficos (`special_role_id`) inmunes a la expiración de membresías.
- **Backups Automatizados**:
  - Volcados completos PostgreSQL cada 12 horas en `backups/sql/` con retención rotativa y actualización de enlace `latest.sql`.
