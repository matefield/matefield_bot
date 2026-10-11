# Wardogs RCON Automation - Documento de Conocimiento del Sistema (Versión Actual)

Este documento centraliza el conocimiento arquitectónico, conceptual, de diseño de dominio (DDD) y operativo del ecosistema **Wardogs RCON Automation / Matefield Bot**. Sirve como la fuente definitiva de verdad para desarrolladores y administradores del proyecto.

---

## 1. Visión y Propósito del Ecosistema

El sistema automatiza la administración integral de servidores del juego **Wardogs** mediante su interfaz **RCON**, sincronizándola en tiempo real con la comunidad de **Discord** y una base de datos relacional centralizada.

### Objetivos Clave
1. **Gestión de Membresías y Slots Reservados**: Garantizar que los usuarios con membresías VIP activas tengan acceso prioritario a los slots reservados del servidor de juego sin intervención humana manual.
2. **Sincronización Bidireccional de Roles**: Mantener sincronizados los roles de Discord con el estado financiero/activo de las membresías en la base de datos (asignación y revocación automática).
3. **Monitoreo y Métricas en Vivo**: Supervisar partidas en tiempo real, estadísticas de combate (kills, deaths, cash), detección de posibles infractores (KPM Monitor) y anuncios globales.
4. **Moderación Unificada**: Sincronizar sanciones (baneos/desbaneos) tanto en el motor del juego (RCON) como en el servidor de Discord.

---

## 2. Arquitectura de Microservicios

El proyecto implementa una arquitectura desacoplada basada en contenedores Docker y administrada con el gestor de paquetes moderno **uv**:

```
 ┌────────────────┐          HTTP / REST          ┌─────────────────┐
 │                │ ────────────────────────────> │                 │
 │  Discord Bot   │   (API Key Guard en /v1/..)   │    API RCON     │
 │ (Hikari-Cresc) │ <──────────────────────────── │    (FastAPI)    │
 └────────────────┘                               └────────┬────────┘
         │                                                 │
         │ Discord API                                     │
         ▼                                                 │
 ┌────────────────┐                 ┌──────────────────────┴──────────────────────┐
 │ Servidor de    │                 ▼                                             ▼
 │ Discord        │      ┌────────────────────┐                        ┌────────────────────┐
 └────────────────┘      │  PostgreSQL 15 DB  │                        │  Servidor RCON     │
                         │(asyncpg/SQLModel)  │                        │  (Juego / Mock)    │
                         └────────────────────┘                        └────────────────────┘
```

### Componentes:
- **`apps/discord_bot`**:
  - Construido sobre **Hikari** (gateway asíncrono de Discord) y **Crescent** (framework tipado de slash commands).
  - Actúa como la interfaz de usuario para la comunidad y el panel de control para administradores.
  - No accede directamente a la base de datos ni al socket de RCON; delega toda la lógica de negocio a la API REST.
- **`apps/api_rcon`**:
  - Construido con **FastAPI** y **SQLModel / SQLAlchemy** asíncrono (`asyncpg`).
  - Único punto de contacto con la base de datos PostgreSQL y con el protocolo RCON del servidor de juego.
  - Implementa un guard de seguridad por encabezado `X-API-Key`.
- **`apps/rcon_mock`**:
  - Servidor emulador de la API RCON oficial de Wardogs (puerto interno `7776`, expuesto en `9001`).
  - Replica fielmente endpoints de estado (`/v1/status`), jugadores (`/v1/players`), slots reservados (`/v1/reserved-slots`), comandos de admin y mapas.
  - Permite pruebas E2E 100% realistas en local sin tocar producción.
- **`packages/wardogs_schemas`**:
  - Paquete interno de esquemas Pydantic compartidos para tipado estricto entre servicios.

---

## 3. Modelo de Dominio (DDD): Roles vs Membresías

Una decisión arquitectónica fundamental de esta versión es la separación estricta entre **Membresías** y **Roles**:

### A. Membresías (`Membership`)
- **Definición**: Es un derecho temporal o vitalicio a beneficios técnicos en el juego, principalmente **acceso a Slots Reservados (Queue Skip)**.
- **Ciclo de Vida**:
  - Tiene fecha de inicio (`start_time`), fecha de caducidad (`end_time`), y bandera computada/persistida (`is_active`).
  - Si `end_time` es `NULL`, representa una membresía permanente (vitalicia).
  - Al expirar (`end_time < now`), el motor de sincronización la desactiva y remueve el Steam ID de los slots reservados del servidor RCON.

### B. Roles (`Role` y `PlayerRole`)
- **Definición**: Representa la identidad, jerarquía de permisos o distinciones del jugador tanto en el sistema como en Discord.
- **Tipología de Roles (`role_type`)**:
  - **`SYSTEM`**: Roles de administración del sistema (**Admins / Supervisores**). Permiten acceso a comandos protegidos.
  - **`VIP`**: Roles asignados a donadores o usuarios con beneficios premium.
  - **`PUBLIC`**: Roles públicos de identidad o menciones en Discord.
  - **`SPECIAL`**: Roles honoríficos, de eventos o distinciones únicas.
- **Mapeo a Discord**: Cada rol en la tabla `roles` puede vincularse a un `discord_role_id` numérico.

### C. Unificación de Jerarquía Administrativa: Adiós al "Owner"
- En versiones anteriores existía una separación ficticia e inconsistente entre "Owner" y "Admin", lo que causaba desincronizaciones en la base de datos y en los permisos de Discord.
- **Regla de Negocio Actual**: El concepto de "Owner" no existe como entidad separada. Todos los miembros del staff con permisos de administración son tratados de forma unificada bajo la categoría **ADMIN / SUPERVISOR**. Los roles de tipo `SYSTEM` otorgan control administrativo completo sin excepciones arbitrarias.

### D. Vinculación de `MembershipType` con `roles.id` y Doble Precio
- Anteriormente existía duplicidad entre `membership_types` y la tabla `roles`, además de configuraciones dispersas en `bot_config` y la tabla obsoleta `membership_type_configs`.
- **Refactorización**:
  - `membership_types.role_id` referencia directamente a `roles.id`, unificando el paquete con su rol de tipo `VIP`. La columna redundante `discord_role_id` fue completamente eliminada de `membership_types` en la migración `k7g8b9c0d1e2`. El ID de Discord se resuelve dinámicamente desde el rol asociado.
  - **Doble Precio**: Se soportan transparentemente `base_price_usd` (precio neto real, ej. $5.00 / $3.00) y `price_usd` (precio listado de venta, ej. $6.00 / $4.00), visualizados en `/membership_type list`. Permitiendo valor `NULL` o 0 para membresías de recompensa.

### E. Ciclo de Vida en `player_roles` según `role_type` y Roles Especiales Adjuntos
- La tabla `memberships` cuenta con dos claves foráneas explícitas hacia `roles.id`:
  - `role_granted_id`: El rol VIP correspondiente a la membresía adquirida (de `membership_types.role_id`).
  - `special_role_id`: Un rol especial adicional o conmemorativo que puede adjuntarse a la membresía (ej. "VIP Fundador" o "Fundador").
- La tabla asociativa `player_roles` almacena la relación universal jugador-rol `(steam_id, role_id)`.
- Al expirar una membresía, solo los roles con `role_type == 'VIP'` (`role_granted_id`) son revocados de `player_roles` y de Discord cuando el jugador no tiene otra membresía activa que los otorgue.
- Los roles especiales adjuntos (`special_role_id`) y del sistema (`role_type in ('SPECIAL', 'SYSTEM')`) son **inmunes a la expiración** de suscripciones; nunca se eliminan automáticamente salvo revocación explícita por un administrador. Además, al renovar o extender una membresía existente, el rol especial adjunto se hereda automáticamente.
- En `/player profile`, solo los roles con `role_type == 'SPECIAL'` aparecen listados en "Roles Especiales", y los datos confidenciales ("Rango RCON" y "Observaciones Internas") solo son visibles si quien ejecuta el comando es un Administrador.

---

## 4. Filosofía de Comandos del Bot: "Entidades Primero"

Todos los comandos de barra (`/`) del bot de Discord están organizados bajo el principio de **Entidades Primero**: `/<entidad> <acción>`. Esto reemplaza la antigua agrupación técnica (como `/db ...` o `/admin ...`) por un lenguaje ubicuo centrado en el dominio:

| Entidad Principal | Subcomandos / Acciones | Propósito de Negocio |
| :--- | :--- | :--- |
| **`/membership`** | `add`, `list`, `edit`, `remove`, `sync`, `compensate_all`, `extend` | Gestión de suscripciones VIP, prórrogas y sincronización |
| **`/roles`** | `register`, `list`, `assign`, `remove` | Catálogo de roles DDD y asignación directa a jugadores |
| **`/player`** | `link`, `unlink`, `profile`, `list`, `edit`, `welcome_message_set` | Identidad del jugador, vinculación Discord-Steam y perfil |
| **`/server`** | `status`, `announce`, `set_max_reserved`, `logs` | Operaciones en vivo sobre el servidor RCON de juego |
| **`/match`** | `status`, `players`, `leaderboard`, `player_info` | Telemetría en tiempo real de la partida en curso |
| **`/ban`** | `add`, `remove`, `list` | Sanciones disciplinarias coordinadas RCON + Discord |
| **`/ban_role`** | `map`, `unmap`, `list` | Vinculación de roles de castigo de Discord según duración |
| **`/quota`** | `list`, `set` | Control de límites y cupos máximos por tipo de VIP |
| **`/reserved_slots`**| `list`, `add`, `remove`, `sync_status` | Inspección directa de slots reservados en el RCON |
| **`/leaderboard`** | `list` | Tablas de clasificación históricas por kills, muertes o cash |
| **`/whitelist`** | `add`, `remove`, `list` | Lista blanca de Discord inmune a la desincronización de roles |
| **`/config`** | `announcement_channel`, `match_channel`, `list` | Canales de notificación del servidor de Discord |

---

## 5. Motores de Sincronización y Automatizaciones

### 1. Sincronizador de Membresías (`membership_monitor` y `/sync_memberships`)
- **Frecuencia**: El bot ejecuta la tarea en segundo plano cada 60 segundos.
- **Acciones**:
  1. La API evalúa qué membresías han caducado en la base de datos y las marca inactivas.
  2. La API envía a RCON la lista actualizada de Steam IDs activos para los slots reservados.
  3. La API responde al bot con la lista completa de usuarios vinculados, sus roles correspondientes y el mapa de roles de Discord.
  4. El bot recorre los usuarios en el servidor de Discord:
     - Asigna los roles que les corresponden según sus membresías/roles activos.
     - Remueve los roles de membresías que han expirado o fueron canceladas.
     - Respeta estrictamente la `WHITELIST` para evitar alterar cuentas protegidas.

### 2. Monitor de Partidas y Premio MVP (`match_monitor`)
- El bot sondea cada 10 segundos el estado del servidor RCON.
- Al detectarse el fin de una partida (un equipo alcanza la puntuación límite o el estado cambia):
  - Registra las estadísticas finales del match en `matches`, `match_team_stats` y `match_player_stats`.
  - Identifica al jugador con más asesinatos (MVP de la partida).
  - Otorga automáticamente **1 día de membresía VIP de regalo** (`VIP_MVP_GIFT`) al MVP e inserta el registro en la BD.
  - Publica el anuncio oficial en el canal de resultados de Discord y envía un broadcast in-game.

### 3. Mensajes de Bienvenida VIP / Staff (`vip_monitor`)
- Cuando un jugador con rol VIP o ADMIN se conecta al servidor, el bot detecta su ingreso y recupera su `custom_welcome_message` de la base de datos.
- Envía un mensaje broadcast en pantalla al servidor de juego anunciando su entrada.

### 4. Sistema Anti-Hack KPM (`hacker monitor`)
- Permite a un administrador auditar en tiempo real a un jugador sospechoso mediante `/hacker monitor`.
- Calcula periódicamente las muertes por minuto (*Kills Per Minute - KPM*). Si supera el umbral crítico, dispara alertas visuales con controles interactivos para aplicar kick o ban inmediato.

---

## 6. Comportamiento y Resiliencia ante Reinicios del Servidor

Los servidores de juego programan reinicios periódicos para mantenimiento o cambio de ciclo. El sistema está diseñado para tolerar estas interrupciones:
1. **Detección de Caída**: Cuando RCON se reinicia o se corta la conexión socket/HTTP, el cliente de la API captura las excepciones de red (`ConnectionRefusedError`, `TimeoutError`, HTTP 502/503).
2. **Sin Corrupción de Estado**: Las membresías y perfiles residen en PostgreSQL, por lo que una caída del servidor de juego no altera los registros de la base de datos.
3. **Reconexión Automática**: El motor de pooling y las tareas de Discord reintentan la conexión en el siguiente ciclo sin crashear el bot.
4. **Resincronización Inmediata al Volver**: Al retornar el servidor RCON en línea, el siguiente ciclo de `/sync_memberships` reinyecta automáticamente la lista completa de slots reservados desde PostgreSQL a la memoria del servidor de juego.
