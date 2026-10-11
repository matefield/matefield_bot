# Matefield mock RCON in Docker

The versioned `infra/warcon/compose.override.yml` connects Warcon's web and worker services to the
`matefield-discord-bot_matefield_local_net` bridge. The Matefield bot's
`mock_rcon_1` service exposes the DNS alias `mock-rcon` on this network.
Warcon's database and relay keep using its existing default network.

Keep the Warcon checkout at `/home/nono/dev/projects/warcon`. This override is
stored in the Matefield repository; it does not require changes to Warcon.
Start the mock first, then Warcon:

```sh
cd /home/nono/dev/projects/matefield-discord-bot
docker compose -f docker-compose.local.yml up -d --build --no-deps mock_rcon_1

cd /home/nono/dev/projects/warcon
docker compose -f docker-compose.yml \
  -f /home/nono/dev/projects/matefield-discord-bot/infra/warcon/compose.override.yml up -d
```

In Warcon, the **MATEFIELD LOCAL** organisation and server use:

| Setting | Value |
| --- | --- |
| Scheme | `http` |
| Host | `mock-rcon` |
| Port | `7776` |
| RCON password | `test` (the mock's fictional password) |

Private Docker targets must be registered by Warcon's site owner. This server
has the private-target allowance. The panel is at <http://localhost:3000>.
On a fresh database, create the organisation and then its server from the panel
using the settings above; the local setup uses Warcon's supported API for both.

The mock returns simulated status and 80 players initially. It serves the
catalogs required by Warcon's server layout, plus the read-only rotation,
capabilities, health and sponsor endpoints used by the overview. Its capabilities
do not advertise unsupported config, rotation or live-settings writes.

It does not implement the complete Wardogs API: server ID reads are missing,
and its config response does not include the structured sections Warcon requires.
Config, live settings and rotation editing are not advertised as supported.
Ban-list and reserved-slot endpoints remain available for local tests.

This override is for local development. To run the original Warcon stack without
the mock network, explicitly select `docker compose -f docker-compose.yml up -d`.
If the mock stack is brought down, start it again before recreating Warcon.
