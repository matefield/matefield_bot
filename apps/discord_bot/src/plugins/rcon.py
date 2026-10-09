import logging

import crescent
import hikari

from src.groups import rcon_group
from src.model import Model
from src.ui_utils import format_api_error

logger = logging.getLogger("wardogs.rcon")
plugin = crescent.Plugin[hikari.GatewayBot, Model]()


@plugin.include
@rcon_group.child
@crescent.command(name="list", description="Lista los servidores RCON configurados")
class RconList:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            servers = await plugin.model.api.get_rcon_servers()
            if not servers:
                await ctx.respond("⚠️ No hay servidores RCON registrados en la base de datos. Se está usando la configuración de respaldo de `.env`.")
                return

            embed = hikari.Embed(
                title="📡 Servidores RCON Configurados",
                description=f"Total: **{len(servers)}** servidor(es)",
                color=0x2ECC71
            )

            for s in servers:
                status_icon = "🟢 Activo" if s.is_active else "🔴 Inactivo"
                default_badge = " ⭐ (Predeterminado)" if s.is_default else ""
                val = (
                    f"**URL:** `{s.scheme}://{s.ip}:{s.port}`\n"
                    f"**Estado:** {status_icon}{default_badge}\n"
                    f"**ID:** `{s.id}`"
                )
                embed.add_field(name=f"🖥️ {s.name or 'Sin nombre'}", value=val, inline=False)

            await ctx.respond(embed=embed)
        except Exception as e:
            logger.exception("Error listando servidores RCON")
            await ctx.respond(f"❌ Error al obtener los servidores: {format_api_error(e)}")


@plugin.include
@rcon_group.child
@crescent.command(name="add", description="Añade un nuevo servidor RCON a la base de datos")
class RconAdd:
    ip = crescent.option(str, "Dirección IP o host del servidor")
    puerto = crescent.option(int, "Puerto RCON del servidor")
    password = crescent.option(str, "Contraseña RCON")
    nombre = crescent.option(str, "Nombre descriptivo (opcional: se autodetecta por RCON si se omite)", default=None)
    esquema = crescent.option(str, "Esquema de conexión", choices=(("HTTP", "http"), ("HTTPS", "https")), default="http")
    activo = crescent.option(bool, "¿Activar servidor para sincronizaciones?", default=True)
    default = crescent.option(bool, "¿Establecer como servidor predeterminado?", default=False)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            name_val = str(self.nombre).strip() if self.nombre else None
            result = await plugin.model.api.create_rcon_server(
                ip=str(self.ip).strip(),
                port=int(self.puerto),
                password=str(self.password).strip(),
                name=name_val,
                scheme=str(self.esquema),
                is_active=bool(self.activo),
                is_default=bool(self.default)
            )

            server = result.server
            if not server:
                await ctx.respond("❌ Servidor registrado, pero no se devolvieron detalles.")
                return
            embed = hikari.Embed(
                title="✅ Servidor RCON Registrado",
                color=0x2ECC71
            )
            embed.add_field(name="ID", value=f"`{server.id}`", inline=True)
            embed.add_field(name="Nombre", value=f"**{server.name}**", inline=True)
            embed.add_field(name="Dirección", value=f"`{server.scheme}://{server.ip}:{server.port}`", inline=False)
            embed.add_field(name="Activo", value="Sí" if server.is_active else "No", inline=True)
            embed.add_field(name="Predeterminado", value="Sí ⭐" if server.is_default else "No", inline=True)

            await ctx.respond(embed=embed)
        except Exception as e:
            logger.exception("Error añadiendo servidor RCON")
            await ctx.respond(f"❌ Error al registrar servidor RCON: {format_api_error(e)}")


@plugin.include
@rcon_group.child
@crescent.command(name="test", description="Prueba la conectividad de un servidor RCON")
class RconTest:
    server_id = crescent.option(int, "ID del servidor RCON a probar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            res = await plugin.model.api.test_rcon_server(int(self.server_id))
            online = res.is_online
            color = 0x2ECC71 if online else 0xE74C3C
            status_text = "🟢 ONLINE" if online else "🔴 OFFLINE"

            embed = hikari.Embed(
                title=f"Diagnóstico RCON: {res.server_name or 'Servidor'}",
                color=color
            )
            embed.add_field(name="ID Servidor", value=f"`{self.server_id}`", inline=True)
            embed.add_field(name="Estado", value=f"**{status_text}**", inline=True)
            embed.add_field(name="Latencia", value=f"`{res.latency_ms or 0} ms`", inline=True)

            if online:
                embed.add_field(name="Mapa Actual", value=f"🗺️ `{res.current_map or 'Desconocido'}`", inline=True)
                embed.add_field(name="Jugadores", value=f"👥 `{res.player_count or 0}/{res.max_players or 0}`", inline=True)
            else:
                embed.add_field(name="Detalle de error", value=f"```\n{res.error or 'Sin respuesta'}\n```", inline=False)

            await ctx.respond(embed=embed)
        except Exception as e:
            logger.exception("Error testeando servidor RCON")
            await ctx.respond(f"❌ Error al realizar la prueba: {format_api_error(e)}")


@plugin.include
@rcon_group.child
@crescent.command(name="edit", description="Modifica los parámetros de un servidor RCON")
class RconEdit:
    server_id = crescent.option(int, "ID del servidor RCON a editar")
    nombre = crescent.option(str, "Nuevo nombre del servidor", default=None)
    ip = crescent.option(str, "Nueva dirección IP", default=None)
    puerto = crescent.option(int, "Nuevo puerto", default=None)
    password = crescent.option(str, "Nueva contraseña", default=None)
    esquema = crescent.option(str, "Nuevo esquema", choices=(("HTTP", "http"), ("HTTPS", "https")), default=None)
    activo = crescent.option(bool, "Estado activo", default=None)
    default = crescent.option(bool, "Marcar como predeterminado", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            update_payload = {}
            if self.nombre is not None:
                update_payload["name"] = str(self.nombre).strip()
            if self.ip is not None:
                update_payload["ip"] = str(self.ip).strip()
            if self.puerto is not None:
                update_payload["port"] = int(self.puerto)
            if self.password is not None:
                update_payload["password"] = str(self.password).strip()
            if self.esquema is not None:
                update_payload["scheme"] = str(self.esquema)
            if self.activo is not None:
                update_payload["is_active"] = bool(self.activo)
            if self.default is not None:
                update_payload["is_default"] = bool(self.default)

            if not update_payload:
                await ctx.respond("⚠️ No especificaste ningún campo para modificar.")
                return

            res = await plugin.model.api.update_rcon_server(self.server_id, **update_payload)
            if res.server:
                await ctx.respond(f"✅ Servidor `{self.server_id}` (**{res.server.name}**) actualizado correctamente.")
            else:
                await ctx.respond(f"✅ Servidor `{self.server_id}` actualizado correctamente.")
        except Exception as e:
            logger.exception("Error editando servidor RCON")
            await ctx.respond(f"❌ Error al actualizar servidor: {format_api_error(e)}")


@plugin.include
@rcon_group.child
@crescent.command(name="remove", description="Elimina un servidor RCON de la base de datos")
class RconRemove:
    server_id = crescent.option(int, "ID del servidor RCON a eliminar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            await plugin.model.api.delete_rcon_server(self.server_id)
            await ctx.respond(f"🗑️ Servidor `{self.server_id}` eliminado con éxito.")
        except Exception as e:
            logger.exception("Error eliminando servidor RCON")
            await ctx.respond(f"❌ Error al eliminar servidor: {format_api_error(e)}")


@plugin.include
@rcon_group.child
@crescent.command(name="sync_all", description="Fuerza sincronización inmediata en todos los servidores RCON activos")
class RconSyncAll:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            res = await plugin.model.api.sync_all_rcon_servers()
            results = res.results

            embed = hikari.Embed(
                title="🔄 Sincronización Multi-Servidor RCON",
                description=f"Total de servidores procesados: **{len(results)}**",
                color=0x3498DB
            )

            for r in results:
                status_icon = "🟢" if r.status == "SUCCESS" else "🔴"
                detail = f"**VIPs:** {r.vip_slots_synced} slots | **Bans:** {r.bans_synced}"
                if r.error:
                    detail += f"\n*Error:* `{r.error}`"
                embed.add_field(
                    name=f"{status_icon} {r.server_name} (`{r.server_id}`)",
                    value=detail,
                    inline=False
                )

            await ctx.respond(embed=embed)
        except Exception as e:
            logger.exception("Error sincronizando servidores RCON")
            await ctx.respond(f"❌ Error durante la sincronización: {format_api_error(e)}")
