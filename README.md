# Wardogs Server RCON Automation

Este proyecto es una solución integral para automatizar la gestión y monitoreo de un servidor de juegos a través de RCON. Permite registrar estadísticas de partidas, manejar roles VIP dinámicamente y ofrecer comandos de administración a través de Discord.

## Arquitectura del Proyecto

El sistema está construido con un enfoque de microservicios usando **Docker Compose**, lo que facilita el despliegue tanto en entornos locales (desarrollo) como en producción.

- **`api_rcon`** (FastAPI + SQLModel + AsyncPG): Es el núcleo del sistema. Se encarga de:
  - Comunicarse con uno o múltiples servidores de juego concurrentemente mediante RCON (`aiohttp`).
  - Polling periódico global (Multi-Server) del estado del servidor para detectar cambios de mapas y resultados de partidas (`sync_engine`).
  - Proveer una API REST modularizada (`/api/v1`) para lectura y manipulación de la base de datos (jugadores, roles, membresías, estadísticas).
  - Gestionar las migraciones de base de datos a través de **Alembic**.

- **`discord_bot`** (Hikari + Crescent): Un bot de Discord robusto que interactúa únicamente con la `api_rcon`.
  - Escucha eventos y comandos de los administradores en Discord.
  - Ejecuta automatizaciones programadas (ej. `[VIP Monitor]`, `[Match Monitor]`, alineación de roles DDD y desbaneos automáticos).

- **`postgres-db`** (PostgreSQL 15): Base de datos relacional del proyecto.
- **`rcon-mock`** (FastAPI): Un servidor de pruebas local que simula las respuestas del servidor RCON real, útil para desarrollo sin depender del servidor en vivo.

## Estructura de Directorios

```text
.
├── apps/
│   ├── api_rcon/       # Backend FastAPI, motor de sincronización y webhooks Tebex.
│   ├── discord_bot/    # Bot de Discord (Hikari + Crescent).
│   └── rcon_mock/      # Servidor mock de RCON para desarrollo.
├── packages/           # Dependencias internas compartidas (wardogs_schemas, wardogs_config).
├── docs/               # Documentación técnica, manual de comandos y planes de migración.
├── backups/            # Backups de base de datos en SQL y CSV (ignorado por Git).
├── .env.local          # Variables de entorno para pruebas locales en Docker.
├── .env.dev            # Variables de entorno para servidor de desarrollo.
├── .env.prod           # Variables de entorno para producción.
├── docker-compose.local.yml # Orquestación local (con DB y mock RCON).
├── docker-compose.dev.yml   # Orquestación de desarrollo.
└── docker-compose.prod.yml  # Orquestación de producción.
```

## Requisitos Previos

- [Docker](https://www.docker.com/) y Docker Compose.
- [uv](https://github.com/astral-sh/uv) (Gestor de paquetes y dependencias Python ultrarrápido).
- Python 3.13+ (Si se desea correr fuera de Docker).

## Configuración y Despliegue

### 1. Variables de Entorno
Crea o edita los archivos `.env.local`, `.env.dev` o `.env.prod`. Utiliza `.env.example` como plantilla base.

```env
DISCORD_TOKEN=tu_token_de_discord
DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED=true
RCON_URL=http://rcon-mock:7776        # Opcional, el sistema usa la base de datos para registrar multiples RCONs.
RCON_PASSWORD=tu_password_rcon
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
API_KEY=tu_api_key_secreta
API_BASE_URL=http://api_rcon:8000
PUBLIC_API_URL=http://localhost:8000
STEAM_WEB_API_KEY=tu_steam_api_key
```

`DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED` vale `true` por defecto para conservar
la gestión de membresías del bot Python. Si Laracord administra las membresías,
configuralo en `false` tanto en `api_rcon` como en `discord_bot`: Python deja de
registrar sus comandos de membresías y de modificar sus roles, incluidos los
especiales asociados. Los comandos manuales de roles también rechazan esos beneficios
antes de modificar la base de datos; las altas, renovaciones y bajas de membresías
en la API siguen disponibles. El rol LINK y los roles ajenos a membresías siguen activos.
También se deshabilitan los avisos de vencimiento por mensaje privado del bot Python,
los regalos VIP al MVP y los canjes automáticos legacy de membresías o de sus roles;
estos canjes se rechazan antes de gastar puntos o generar vouchers. El mantenimiento de vencimientos de la API continúa funcionando.

El panel de `/player link_channel` usa un botón verde de interacción: Discord identifica a quien lo pulsa.
Si ya tiene Steam vinculado, recibe una confirmación privada. Si no, recibe un enlace privado «Ir a Steam»,
firmado y válido durante diez minutos. No necesita OAuth de Discord web ni una sesión de identidad del navegador.
`PUBLIC_API_URL` debe apuntar a la API desde el navegador de los usuarios, no al hostname interno de Docker;
en producción debe utilizar HTTPS. La pantalla final queda en `/vincular/discord-steam/resultado`.
Al volver a ejecutar `/player link_channel` en el mismo canal se actualiza el mensaje existente.
`/player link` ofrece el mismo recorrido privado. Aplicar `alembic upgrade head` antes de iniciar la API.

### 2. Levantar el Entorno Local
Ejecuta el siguiente comando en la raíz del proyecto para construir y levantar todos los servicios con base de datos local y mock RCON:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

### Pruebas locales con Laracord y Steam

Usá aplicaciones Discord diferentes para cada bot y agregá la aplicación Python
solo al servidor de pruebas. Laracord administra membresías y roles VIP; Python
conserva la vinculación Steam y las demás operaciones. En `.env.local`:

```dotenv
DISCORD_GUILD_ID=ID_DEL_SERVIDOR_DE_PRUEBAS
DISCORD_GUILD_IDS=ID_DEL_SERVIDOR_DE_PRUEBAS
DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED=false
API_BASE_URL=http://matefield-api:8000
```

La API tiene el alias `matefield-api` en la red local de Compose. Laracord debe
conectarse a `matefield-discord-bot_matefield_local_net`, usar ese mismo origen y
la misma `API_KEY`, con su propio token Discord. El bot Python espera que la API
esté saludable antes de iniciar. En Developer Portal, activá **Server Members
Intent** y **Presence Intent** para Python. Su rol debe estar por encima del rol
de vinculación Steam; el de Laracord, por encima de los roles VIP.

Al restaurar una base de producción, configurá sus filas `rcon_servers` para el
mock local antes de iniciar la API: la base tiene prioridad sobre `RCON_URL`.
También configurá los roles, `GUILD_ID` y `LINK_ROLE_ID` para pruebas y retirale
las referencias del panel y de canales de anuncios anteriores.

El perfil opcional `tunnel` publica el recorrido Steam en
`https://matefield-api-dev.openchamba.online`. El acceso a membresías permanece en la red
Docker. Una vez autorizado el dominio en Cloudflare, configurá en `.env.local`:

```dotenv
PUBLIC_API_URL=https://matefield-api-dev.openchamba.online
CLOUDFLARE_TUNNEL_ID=ID_DEL_TUNEL
CLOUDFLARE_TUNNEL_CREDENTIALS_FILE=/home/nono/.cloudflared/ID_DEL_TUNEL.json
```

Conservá el JSON de credenciales fuera del repositorio, accesible al usuario local
UID 1000. El hostname debe estar asociado a ese túnel en Cloudflare y el recorrido
Steam debe ser público, sin una pantalla de autenticación de Cloudflare Access.
Si una aplicación global de Access cubre `openchamba.online` o sus subdominios,
configurá una excepción para el hostname exacto
`matefield-api-dev.openchamba.online`: una aplicación dedicada con política
**Bypass** para **Everyone**. Conservá la protección de la aplicación global y de
los demás dominios. El ingress del túnel sigue limitando este hostname al recorrido
Steam y sus recursos; las operaciones privadas responden `404`.

El certificado local de `cloudflared` usado para administrar el túnel y su DNS no
habilita la gestión de aplicaciones o políticas de Access. Configurá esa excepción
desde el panel de Cloudflare con una cuenta que tenga permisos de Access.

Para cargar las variables y levantarlo:

```bash
docker compose -f docker-compose.local.yml --env-file .env.local up -d --wait api_rcon
docker compose -f docker-compose.local.yml --env-file .env.local up -d discord_bot
docker compose -f docker-compose.local.yml --env-file .env.local --profile tunnel up -d cloudflared
```

El túnel permite login, callback, resultado y recursos de la página Steam; los
demás paths responden `404`. Publicá el panel mediante `/player link_channel` en
el canal de pruebas elegido, o usá `/player link` para obtener un enlace privado.

Al terminar las pruebas, detené los servicios locales con
`docker compose -f docker-compose.local.yml --env-file .env.local --profile tunnel stop`
(sin eliminar volúmenes). Retirá de Cloudflare el DNS, el túnel y la aplicación y
política de Access que se crearon exclusivamente para este hostname. Limpiá las
variables `CLOUDFLARE_TUNNEL_ID` y `CLOUDFLARE_TUNNEL_CREDENTIALS_FILE`, y volvé a
`PUBLIC_API_URL=http://localhost:8000/` en el entorno local.

### Warcon local

La [guía de Warcon local](infra/warcon/README.md) incluye el override de Compose
para conectar el panel y su worker al mock RCON. La configuración se versiona en
este repositorio y se aplica sobre el checkout de Warcon.

### 3. Levantar el Entorno de Producción
Para el entorno en vivo (conectado a la base de datos de producción y servidor RCON real):

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Base de Datos y Migraciones (Alembic)

La base de datos utiliza PostgreSQL y se maneja de forma asíncrona (`asyncpg`). Las migraciones del esquema se realizan mediante **Alembic**.

- **Ejecutar migraciones en local/contenedor**:
  ```bash
  uv run alembic upgrade head
  ```
- **Verificar que no haya discrepancias de esquema**:
  ```bash
  uv run alembic check
  ```

## Pruebas Automatizadas (Tests)

Todas las suites de tests de la API y del bot de Discord se ejecutan en conjunto desde la raíz:
```bash
uv run pytest
```

Las suites cubren CRUD, roles, RCON, webhooks, comandos de Discord y clientes HTTP.

Las regresiones de concurrencia de membresías se omiten por defecto porque
necesitan PostgreSQL real. Para ejecutarlas, creá una base temporal vacía llamada
`matefield_membership_regression_<sufijo>` y configurá su URL `postgresql+asyncpg`
en `MEMBERSHIP_POSTGRES_TEST_URL`. Luego ejecutá:

```bash
uv run pytest apps/api_rcon/tests/test_membership_concurrency_postgres.py
```

Estas pruebas comprueban los bloqueos del último cupo, el orden de las entregas
y la exclusión mutua entre desasignaciones, altas y configuraciones de roles;
usan Warcon simulado y crean y eliminan tablas solamente en esa base temporal.


Las migraciones de membresías y las de squads se unen en el head
`29f437dc92a1`. Las bases existentes en `p2l3g4h5i6j7` o `0132aeb12a1c`
aplican la rama pendiente con `alembic upgrade head`. La revisión de creación
idempotente usa ahora `7bd48ca30901` para evitar reutilizar el ID de global seeding.

Para verificar una instalación vacía y ambos caminos de actualización, usá otra
base temporal vacía con el mismo prefijo y configurá su URL en
`MEMBERSHIP_MIGRATION_POSTGRES_TEST_URL`:

```bash
uv run pytest apps/api_rcon/tests/test_membership_migrations_postgres.py
```

La suite comprueba el esquema final y que los datos existentes permanezcan
iguales; limpia sus tablas y enums después de cada caso. La creación y eliminación
de la base temporal queda a cargo de quien ejecuta las pruebas.

## Motor de Sincronización Automática (Multi-Server Polling)
La aplicación incluye un motor en segundo plano (`sync_engine.py`) embebido en FastAPI diseñado para entornos multi-servidor:
1. **Concurrencia Multi-Server:** Consulta continuamente (polling) los endpoints RCON de todos los servidores registrados en la tabla `rcon_servers` que estén activos.
2. **Ciclo de Partidas:** Compara el estado actual (ej. mapa) con el anterior de manera aislada para cada servidor detectando las transiciones y finales de partidas.
3. **Session Tracking Global:** Consolida el tiempo de juego de los jugadores sin importar a qué servidor del clúster estén conectados. Si un jugador está en el Servidor 1, no se considerará desconectado por el Servidor 2, eliminando posibles condiciones de carrera.
4. **Sincronización en Tiempo Real:** Las inyecciones de slots reservados RCON y las asignaciones de roles VIP en Discord ocurren **en tiempo real** al utilizar los comandos del bot (`/membership add`, `/roles give`, `/membership remove`, etc), usando el loop del engine en segundo plano solo para mantenimiento y caducidad de membresías (cada 5 minutos).

### Roles de membresía por servidor de Discord

La API almacena `role_discord_bindings`: un vínculo entre el rol lógico de cada
membresía y su rol concreto en un servidor de Discord. Configurá en el entorno de
la API `DISCORD_GUILD_IDS` con los IDs habilitados separados por coma. Si está
vacío se utiliza `DISCORD_GUILD_ID`; sin configuración el acceso se rechaza.
Esta lista corresponde a servidores de una misma comunidad: las membresías
continúan siendo globales y no se comparte automáticamente con otros servidores.

Laracord valida los permisos del administrador y que pueda administrar el rol.
Luego guarda mediante `PUT /api/v1/discord/guilds/{guild_id}/membership-types/{code}/role`
con `{ "discord_role_id": "...", "actor_id": "..." }`, autenticado por `X-API-Key`.
`GET` en esa misma ruta permite consultar la configuración. No se modifica la
membresía, no se asignan roles existentes y no se llama a Warcon al configurar.
Cambiar a otro rol se rechaza mientras haya membresías vigentes que lo otorgan;
una migración de usuarios requiere una operación explícita.

`DELETE` en esa misma ruta, con `{ "actor_id": "..." }`, elimina el vínculo del
servidor indicado y devuelve `MembershipRoleUnassignment`. La respuesta identifica
el tipo y rol lógico, el administrador, `changed` y el `discord_role_id` anterior
(`null` si el vínculo ya estaba ausente). La operación es idempotente y acepta
limpiar un tipo desactivado. Solo elimina `RoleDiscordBinding`; conserva membresías,
roles de usuarios, IDs globales y Warcon. La auditoría se registra después del commit.

Una baja que modificaría un vínculo devuelve `409` con
`detail.code=membership_role_in_use` si hay membresías vigentes que usan el rol
lógico, o `membership_role_shared` si otro tipo comparte ese rol lógico. La
comprobación de vigencia es global, igual que al cambiar el vínculo. Se usa el
mismo bloqueo de `Role` que en configuración y alta para evitar carreras. Un vínculo
ya ausente devuelve `changed=false` sin modificar datos, incluso si el rol se usa
en otro servidor. Laracord expone esta operación mediante
`/memberships unassign-role`, valida Administrador y traduce los resultados.

Las altas y los listados de Laracord envían `guild_id`. El listado valida que el
servidor esté habilitado y muestra los roles vinculados a ese servidor. La API
resuelve los roles VIP y especiales exclusivamente con los vínculos de ese
servidor, y rechaza faltantes
antes de guardar la membresía o llamar a Warcon. Las solicitudes antiguas sin
`guild_id` conservan el comportamiento anterior. No se migran IDs globales ni se
crean vínculos automáticamente. La caducidad y aplicación a usuarios existentes
no forman parte del comando de configuración.
