import asyncio
import logging
import math
import time
from typing import Any
import crescent
import hikari

from src.model import Model
from src.hooks import admin_only
from src.groups import membership_group, membership_type_group, player_group
from src.trace import get_tracer

logger = logging.getLogger(__name__)
plugin = crescent.Plugin[hikari.GatewayBot, Model]()

_cached_types: list[dict] = []
_last_types_fetch: float = 0.0
_types_lock = asyncio.Lock()

async def get_cached_membership_types():
    global _cached_types, _last_types_fetch
    now = time.time()
    if now - _last_types_fetch > 30 or not _cached_types:
        async with _types_lock:
            # Re-check condition after acquiring lock to prevent stampede
            now = time.time()
            if now - _last_types_fetch > 30 or not _cached_types:
                try:
                    _cached_types = await plugin.model.api.get_membership_types(active_only=True)
                    _last_types_fetch = now
                except Exception:
                    pass
    return _cached_types

async def autocomplete_tipo(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    val = str(option.value or "").lower()
    try:
        types = await get_cached_membership_types()
        results = []
        for t in types:
            code = t.code or ""
            name = t.name or code
            price = t.price_usd or 0.0
            price_str = f" (${price})" if price > 0 else ""
            label = f"{name} [{code}]{price_str}"[:100]
            if val in code.lower() or val in name.lower():
                results.append((label, code))
        if results:
            return results[:25]
    except Exception:
        pass
    fallback = ["VIP_COMUN", "VIP_EXPRESS", "VIP_PERMANENTE"]
    return [(t, t) for t in fallback if val in t.lower()]


# -------------------------------------------------------------
# Membership Management Commands (/membership ...)
# -------------------------------------------------------------

@plugin.include
@membership_group.child
@crescent.command(name="add", description="Añade una membresía VIP a un jugador vinculado")
class DbAddMembership:
    usuario = crescent.option(hikari.User, "Usuario de Discord a añadir membresía")
    tipo = crescent.option(
        str,
        "Tipo de membresía a otorgar (autocompletado o escribe uno)",
        autocomplete=autocomplete_tipo
    )
    dias = crescent.option(int, "Duración en días (opcional, sobreescribe default del paquete, 0 = permanente)", default=None)
    rol_especial = crescent.option(
        hikari.Role,
        "Rol especial adicional a asignar (opcional, si se omite usa el del paquete)",
        default=None
    )
    booster = crescent.option(
        bool,
        "¿Es Booster de Discord? (opcional: si se omite, se autodetecta)",
        default=None
    )
    servidor = crescent.option(
        int,
        "ID de servidor RCON específico (opcional: si se omite usa el del paquete)",
        default=None
    )

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        tracer = get_tracer()
        try:
            with tracer.measure("Buscar cuenta de Steam", category="DB", action="FETCH", target=str(self.usuario.id)) as t:
                player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
                if not player_info:
                    t["status"] = "WARN"
                    t["details"] = "Usuario sin cuenta vinculada"
                    await ctx.respond(tracer.append_to_message("❌ Este usuario no tiene una cuenta de Steam enlazada en la base de datos."))
                    return
                
                steam_id = player_info.steam_id
                if not steam_id:
                    t["status"] = "ERROR"
                    t["details"] = "Sin Steam ID"
                    await ctx.respond(tracer.append_to_message("❌ La cuenta no tiene Steam ID asociado."))
                    return
                t["details"] = f"Steam ID: {steam_id}"

            is_booster_val = self.booster
            if is_booster_val is None:
                try:
                    if ctx.guild_id:
                        member = await ctx.app.rest.fetch_member(ctx.guild_id, self.usuario.id)
                        is_booster_val = member.premium_since is not None
                    else:
                        is_booster_val = False
                except Exception:
                    is_booster_val = False

            special_role = str(self.rol_especial.id) if self.rol_especial else None
            with tracer.measure("Registrar membresía en BD", category="DB", action="CREATE", target=f"Steam {steam_id}") as t:
                await plugin.model.api.add_membership(
                    str(steam_id),
                    str(self.tipo),
                    self.dias,
                    special_role,
                    is_booster=is_booster_val,
                    server_id=self.servidor
                )
                t["details"] = f"Tipo: {self.tipo}, Días: {self.dias or 'Default'}, Servidor: {self.servidor or 'Global'}"

            if self.dias is None:
                dias_str = "Predeterminado (paquete)"
            elif self.dias == 0:
                dias_str = "Permanente"
            else:
                dias_str = f"{self.dias} días"
            booster_tag = "⚡ **Booster:** Sí" if is_booster_val else "⚡ **Booster:** No"
            server_tag = f"🌐 **Servidor:** #{self.servidor}" if self.servidor else "🌐 **Alcance:** Global"
            msg = f"✅ Membresía {self.tipo} añadida a <@{self.usuario.id}> ({steam_id})\n⏳ **Duración:** {dias_str} | {booster_tag} | {server_tag}"
            if special_role:
                msg += f"\n(Rol especial <@&{special_role}> asignado en base de datos)"

            with tracer.measure("Sincronizar roles Discord", category="DISCORD", action="SYNC", target=str(self.usuario.id)) as t:
                from src.plugins.tasks import sync_single_user_roles
                sync_res = await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)
                t["details"] = f"Roles: +{sync_res.get('added', 0)} / -{sync_res.get('removed', 0)}"

            if sync_res.get("success"):
                msg += "\n🔄 Roles de Discord sincronizados."

            await ctx.respond(tracer.append_to_message(msg))
        except Exception as e:
            await ctx.respond(tracer.append_to_message(f"❌ Error: {e}"))


@plugin.include
@crescent.hook(admin_only)
@membership_group.child
@crescent.command(name="list", description="Listado de membresías (Paginado)")
class DbMemberships:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        page = 1
        try:
            res = await plugin.model.api.get_paginated_memberships(page=page, limit=10)
            memberships = res.get("memberships", [])
            total = res.get("total", 0)
            
            if not memberships:
                await ctx.respond("No hay membresías registradas.")
                return
                
            embed = hikari.Embed(
                title=f"📋 Listado de Membresías (Pág {page})",
                description=f"Total registradas: {total}",
                color=0x00FF00
            )
            
            for m in memberships:
                status = "🟢 Activa" if m['is_active'] else "🔴 Inactiva"
                booster_str = " | ⚡ **Booster**" if m.get('is_booster') else ""
                end_str = m['end_date'][:10] if m['end_date'] else "Permanente"
                sp_discord_role_id = m.get("special_discord_role_id")
                sp_name = m.get("special_role")
                if sp_discord_role_id:
                    sp_str = f" | **Especial:** <@&{sp_discord_role_id}>"
                elif sp_name:
                    sp_str = f" | **Especial:** `{sp_name}`"
                else:
                    sp_str = ""
                embed.add_field(
                    name=f"[ID: {m.get('id', '?')}] SteamID: {m['steam_id']}", 
                    value=f"**Tipo:** {m['type']} | **Estado:** {status}{booster_str}\n**Vence:** {end_str}{sp_str}", 
                    inline=False
                )
                
            components = [
                ctx.app.rest.build_message_action_row()
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"mem_prev_{page}", label="Anterior")
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"mem_next_{page}", label="Siguiente")
            ]
            
            await ctx.respond(embed=embed, components=components)
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")


def build_player_memberships_view(
    app: Any,
    usuario_id: int,
    memberships: list[dict],
    page: int,
    total: int,
    limit: int = 5
) -> tuple[hikari.Embed, list[hikari.api.MessageActionRowBuilder]]:
    total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1
    embed = hikari.Embed(
        title=f"📋 Historial de Membresías: <@{usuario_id}>",
        description=f"Total de registros: **{total}** | Página **{page}** de **{total_pages}**",
        color=0x9B59B6
    )

    if not memberships:
        embed.description = f"El usuario <@{usuario_id}> no registra membresías en la base de datos."
    else:
        for m in memberships:
            m_id = m.get("id", "?")
            m_type = m.get("type", "DESCONOCIDO")
            is_active = m.get("is_active", False)
            status_str = "🟢 Activa" if is_active else "🔴 Inactiva"
            steam_id = m.get("steam_id", "Desconocido")

            start_val = m.get("start_date")
            start_str = start_val[:19].replace("T", " ") if start_val else "N/A"

            end_val = m.get("end_date")
            end_str = end_val[:19].replace("T", " ") if end_val else "Permanente (Sin fin)"

            sp_role_id = m.get("special_role_id")
            sp_role_name = m.get("special_role")
            sp_discord_role_id = m.get("special_discord_role_id")
            if sp_discord_role_id and sp_role_name:
                sp_role_str = f"<@&{sp_discord_role_id}> ({sp_role_name})"
            elif sp_role_name and sp_role_id:
                sp_role_str = f"`{sp_role_name}` (`{sp_role_id}`)"
            elif sp_discord_role_id:
                sp_role_str = f"<@&{sp_discord_role_id}>"
            elif sp_role_name:
                sp_role_str = f"`{sp_role_name}`"
            elif sp_role_id:
                sp_role_str = f"DB ID: `{sp_role_id}`"
            else:
                sp_role_str = "Ninguno"

            rcon_status = m.get("rcon_sync_status", "PENDING")

            field_name = f"🏷️ Membresía #{m_id} — {m_type}"
            field_value = (
                f"• **Estado:** {status_str} (`is_active={is_active}`)\n"
                f"• **Steam ID:** `{steam_id}`\n"
                f"• **Fecha Inicio:** `{start_str}`\n"
                f"• **Fecha Fin:** `{end_str}`\n"
                f"• **Rol Especial:** {sp_role_str}\n"
                f"• **RCON Sync Status:** `{rcon_status}`"
            )
            embed.add_field(name=field_name, value=field_value, inline=False)

    btn_row = app.rest.build_message_action_row()
    btn_row.add_interactive_button(
        hikari.ButtonStyle.PRIMARY,
        f"pmem_prev_{usuario_id}_{page}",
        label="◀ Anterior",
        is_disabled=(page <= 1)
    )
    btn_row.add_interactive_button(
        hikari.ButtonStyle.PRIMARY,
        f"pmem_next_{usuario_id}_{page}",
        label="Siguiente ▶",
        is_disabled=(page >= total_pages or total == 0)
    )
    return embed, [btn_row]


@plugin.include
@player_group.child
@crescent.command(name="memberships", description="Muestra el historial de membresías de un usuario de Discord (Paginado)")
class PlayerMemberships:
    usuario = crescent.option(hikari.User, "Usuario de Discord a consultar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        page = 1
        limit = 5
        try:
            res = await plugin.model.api.get_paginated_memberships(page=page, limit=limit, discord_id=str(self.usuario.id))
            memberships = res.get("memberships", [])
            total = res.get("total", 0)

            embed, components = build_player_memberships_view(
                ctx.app,
                int(self.usuario.id),
                memberships,
                page,
                total,
                limit
            )
            await ctx.respond(embed=embed, components=components)
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar membresías: {e}")


@plugin.include
@crescent.event
async def on_membership_button_click(event: hikari.InteractionCreateEvent) -> None:
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return
        
    custom_id = event.interaction.custom_id
    if not custom_id.startswith("mem_prev_") and not custom_id.startswith("mem_next_") and not custom_id.startswith("pmem_prev_") and not custom_id.startswith("pmem_next_"):
        return

    if custom_id.startswith("mem_prev_") or custom_id.startswith("mem_next_"):
        current_page = int(custom_id.split("_")[-1])
        is_next = custom_id.startswith("mem_next_")
        new_page = current_page + 1 if is_next else current_page - 1
        
        if new_page < 1:
            new_page = 1
            
        try:
            res = await plugin.model.api.get_paginated_memberships(page=new_page, limit=10)
            memberships = res.get("memberships", [])
            total = res.get("total", 0)
            
            if not memberships and new_page > 1:
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    "No hay más páginas.",
                    flags=hikari.MessageFlag.EPHEMERAL
                )
                return
                
            embed = hikari.Embed(
                title=f"📋 Listado de Membresías (Pág {new_page})",
                description=f"Total registradas: {total}",
                color=0x00FF00
            )
            
            for m in memberships:
                status = "🟢 Activa" if m['is_active'] else "🔴 Inactiva"
                booster_str = " | ⚡ **Booster**" if m.get('is_booster') else ""
                end_str = m['end_date'][:10] if m['end_date'] else "Permanente"
                sp_str = f" | **Especial:** <@&{m.get('special_role')}>" if m.get('special_role') else ""
                embed.add_field(
                    name=f"[ID: {m.get('id', '?')}] SteamID: {m['steam_id']}", 
                    value=f"**Tipo:** {m['type']} | **Estado:** {status}{booster_str}\n**Vence:** {end_str}{sp_str}", 
                    inline=False
                )
                
            components = [
                plugin.app.rest.build_message_action_row()
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"mem_prev_{new_page}", label="Anterior")
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"mem_next_{new_page}", label="Siguiente")
            ]
            
            await event.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                embed=embed,
                components=components
            )
        except Exception as e:
            await event.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                f"❌ Error: {e}",
                flags=hikari.MessageFlag.EPHEMERAL
            )
    elif custom_id.startswith("pmem_prev_") or custom_id.startswith("pmem_next_"):
        parts = custom_id.split("_")
        action = parts[1]
        target_discord_id = int(parts[2])
        current_page = int(parts[3])
        limit = 5

        new_page = current_page - 1 if action == "prev" else current_page + 1
        if new_page < 1:
            new_page = 1

        try:
            res = await plugin.model.api.get_paginated_memberships(page=new_page, limit=limit, discord_id=str(target_discord_id))
            memberships = res.get("memberships", [])
            total = res.get("total", 0)
            total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1

            if new_page > total_pages:
                new_page = total_pages

            embed, components = build_player_memberships_view(
                plugin.app,
                target_discord_id,
                memberships,
                new_page,
                total,
                limit
            )
            await event.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                embed=embed,
                components=components
            )
        except Exception as e:
            await event.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                f"❌ Error: {e}",
                flags=hikari.MessageFlag.EPHEMERAL
            )


@plugin.include
@crescent.hook(admin_only)
@membership_group.child
@crescent.command(name="edit", description="Edita una membresía existente")
class DbEditMembership:
    id_membresia = crescent.option(int, "ID de la membresía (ver /membership list)")
    dias = crescent.option(int, "Nuevos días (0 = permanente)", default=None, min_value=0)
    tipo = crescent.option(str, "Nuevo tipo de membresía", autocomplete=autocomplete_tipo, default=None)
    activa = crescent.option(bool, "¿Está activa?", default=None)
    booster = crescent.option(bool, "¿Es Booster de Discord?", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            await plugin.model.api.edit_membership(
                int(self.id_membresia),
                days=self.dias,
                membership_type=str(self.tipo) if self.tipo else None,
                is_active=self.activa,
                is_booster=self.booster
            )
            from src.plugins.tasks import execute_membership_sync
            asyncio.create_task(execute_membership_sync(ctx.app, plugin.model, target_guild_id=ctx.guild_id))
            await ctx.respond(f"✅ Membresía ID {self.id_membresia} actualizada exitosamente. 🔄 Sincronizando en segundo plano...")
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")


@plugin.include
@crescent.hook(admin_only)
@membership_group.child
@crescent.command(name="remove", description="Elimina una membresía existente permanentemente")
class DbRemoveMembership:
    id_membresia = crescent.option(int, "ID de la membresía (ver /membership list)")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            await plugin.model.api.delete_membership(self.id_membresia)
            from src.plugins.tasks import execute_membership_sync
            asyncio.create_task(execute_membership_sync(ctx.app, plugin.model, target_guild_id=ctx.guild_id))
            await ctx.respond(f"✅ Membresía ID {self.id_membresia} eliminada exitosamente. 🔄 Sincronizando en segundo plano...")
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")


@plugin.include
@crescent.hook(admin_only)
@membership_group.child
@crescent.command(name="export", description="Exporta las membresías y cuentas vinculadas a un CSV descargable")
class DbExportMemberships:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            res = await plugin.model.api.export_memberships()
            download_url = res.get("download_url", "")
            total = res["total_records"]
            filename = res["filename"]
            expires_mins = res["expires_in_seconds"] // 60
            size_kb = round(res["size_bytes"] / 1024, 1)

            # Retrieve file bytes directly to send as a Discord attachment (native download)
            csv_bytes = await plugin.model.api.download_file_bytes(f"/api/v1/db/memberships/export/download/{filename}")
            attachment = hikari.Bytes(csv_bytes, filename)

            embed = hikari.Embed(
                title="📥 Exportación de Membresías",
                description=(
                    f"Se ha generado exitosamente el archivo CSV con las membresías y cuentas vinculadas.\n"
                    f"El archivo ha sido adjuntado a este mensaje para su descarga directa.\n\n"
                    f"*(Generado desde la base de datos con {total} registros)*"
                ),
                color=0x00FF88
            )
            embed.add_field(name="📄 Archivo", value=filename, inline=True)
            embed.add_field(name="👥 Total Membresías", value=str(total), inline=True)
            embed.add_field(name="📦 Tamaño", value=f"{size_kb} KB", inline=True)
            embed.add_field(
                name="🛡️ Columnas incluidas",
                value="DiscordID, SteamID, Nickname, Tipo VIP, Booster, Fundador, Rol Vinculado, Vigencia y Observaciones.",
                inline=False
            )

            # Discord rejects link buttons with internal docker/non-FQDN URLs (error 50035).
            # Only add the web link button if download_url is a valid public web URL.
            is_public_url = download_url.startswith("https://") or (
                download_url.startswith("http://")
                and "." in download_url.split("/")[2]
                and not download_url.split("/")[2].startswith("localhost")
            )

            if is_public_url:
                button_row = (
                    ctx.app.rest.build_message_action_row()
                    .add_link_button(download_url, label="Descargar vía Web")
                )
                await ctx.respond(embed=embed, attachment=attachment, components=[button_row])
            else:
                await ctx.respond(embed=embed, attachment=attachment)
        except Exception as e:
            await ctx.respond(f"❌ Error al generar exportación: {e}")


@plugin.include
@crescent.hook(admin_only)
@membership_group.child
@crescent.command(name="sync", description="Fuerza la sincronización completa de membresías en BD, slots RCON y roles de Discord")
class ForceSyncMemberships:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        from src.plugins.tasks import execute_membership_sync
        
        try:
            bot_app = getattr(ctx, "app", None)
            try:
                if not bot_app:
                    bot_app = plugin.app
            except Exception:
                pass

            bot_model = None
            try:
                bot_model = plugin.model
            except Exception:
                pass
            if not bot_model:
                bot_model = getattr(ctx, "model", None)

            if not bot_app or not bot_model:
                await ctx.respond("❌ El bot o el cliente API no están listos.")
                return

            stats = await execute_membership_sync(bot_app, bot_model, target_guild_id=ctx.guild_id)
            if not stats.get("success"):
                await ctx.respond(f"❌ Error en sincronización: {stats.get('error', 'Error desconocido')}")
                return

            embed = hikari.Embed(
                title="🔄 Sincronización Completa de Membresías",
                description="Se ha ejecutado la sincronización en base de datos, servidores de juego (RCON) y Discord.",
                color=0x2ECC71
            )
            embed.add_field(name="🎮 Slots Reservados RCON", value=f"`{stats.get('active_rcon_slots', 0)}` activos inyectados", inline=True)
            embed.add_field(name="⏰ Membresías Expiradas", value=f"`{stats.get('expired_count', 0)}` desactivadas", inline=True)
            embed.add_field(name="👥 Jugadores Evaluados", value=f"`{stats.get('users_checked', 0)}` cuentas vinculadas", inline=True)
            embed.add_field(name="➕ Roles Añadidos", value=f"`{stats.get('roles_added', 0)}` otorgados", inline=True)
            embed.add_field(name="➖ Roles Removidos", value=f"`{stats.get('roles_removed', 0)}` revocados", inline=True)
            if stats.get('whitelist_skipped', 0) > 0:
                embed.add_field(name="🛡️ Whitelist", value=f"`{stats.get('whitelist_skipped', 0)}` protegidos", inline=True)
                
            await ctx.respond(embed=embed)
        except Exception as e:
            logger.error(f"Error durante /membership sync: {e}", exc_info=True)
            await ctx.respond(f"❌ Error al ejecutar la sincronización: {e}")


@plugin.include
@crescent.hook(admin_only)
@membership_group.child
@crescent.command(name="compensate_all", description="Extiende todas las membresías activas por la cantidad de días indicados")
class CompensarTodos:
    dias = crescent.option(int, "Cantidad de días a extender")
    
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            res = await plugin.model.api.compensate_memberships(self.dias)
            msg = res.get("message", "Compensación completada.")
            await ctx.respond(f"✅ {msg}")
        except Exception as e:
            await ctx.respond(f"❌ Error al compensar: {e}")


@plugin.include
@crescent.hook(admin_only)
@membership_group.child
@crescent.command(name="extend", description="Extiende una membresía individual por ID")
class ExtenderMembresia:
    membership_id = crescent.option(int, "ID numérico de la membresía")
    dias = crescent.option(int, "Cantidad de días extra")
    
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            await plugin.model.api.edit_membership(membership_id=self.membership_id, add_days=self.dias)
            from src.plugins.tasks import execute_membership_sync
            asyncio.create_task(execute_membership_sync(ctx.app, plugin.model, target_guild_id=ctx.guild_id))
            await ctx.respond(f"✅ Membresía #{self.membership_id} extendida por {self.dias} días exitosamente. 🔄 Sincronizando en segundo plano...")
        except Exception as e:
            await ctx.respond(f"❌ Error al extender membresía: {e}")


# -------------------------------------------------------------
# Membership Types Management Commands (/membership_type ...)
# -------------------------------------------------------------

@plugin.include
@crescent.hook(admin_only)
@membership_type_group.child
@crescent.command(name="list", description="Lista todos los paquetes y tipos de membresía configurados")
class DbMembershipTypeList:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            types = await plugin.model.api.get_membership_types()
            if not types:
                await ctx.respond("ℹ️ No hay tipos de membresía registrados.")
                return

            embed = hikari.Embed(
                title="📦 Catálogo de Tipos de Membresía / Paquetes",
                color=0x3498DB,
                description="Listado de paquetes configurados con cupos, precios y alcance de servidor."
            )

            for t in types:
                code = t.code
                name = t.name or code
                price = t.price_usd or 0.0
                billing = "Mensualidad" if t.billing_type == "RECURRING" else "Pago Único"
                days = t.default_days or 30
                days_str = "Permanente" if days == 0 else f"{days} días"
                max_q = t.max_quota
                used_q = t.current_usage or 0
                quota_str = f"{used_q}/{max_q}" if max_q is not None else f"{used_q} (Ilimitado)"
                server_name = t.server_name or "Global (Todos)"
                role_id = t.discord_role_id
                role_name = t.role_name
                
                if role_id:
                    role_str = f"<@&{role_id}>"
                elif role_name:
                    role_str = f"DB: `{role_name}`"
                else:
                    role_str = "Ninguno"

                status_icon = "🟢" if t.is_active else "🔴 (Inactivo)"

                price_line = f"💵 **Precio:** ${price:.2f} USD ({billing})\n"

                field_value = (
                    price_line +
                    f"⏳ **Duración:** {days_str}\n"
                    f"👥 **Cupos Activos:** {quota_str}\n"
                    f"🌐 **Servidor:** {server_name}\n"
                    f"🛡️ **Rol:** {role_str}\n"
                    f"🏷️ **Estado:** {status_icon}"
                )
                embed.add_field(name=f"#{t.get('id')} - {name} (`{code}`)", value=field_value, inline=True)

            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar tipos de membresía: {e}")


@plugin.include
@crescent.hook(admin_only)
@membership_type_group.child
@crescent.command(name="create", description="Crea un nuevo paquete o tipo de membresía")
class DbMembershipTypeCreate:
    codigo = crescent.option(str, "Código único (ej: VIP_GOLD, VIP_SERVER1)")
    nombre = crescent.option(str, "Nombre amigable (ej: VIP Oro Global)")
    precio = crescent.option(float, "Precio en USD (ej: 6.00)", default=0.0)
    dias = crescent.option(int, "Días de duración por defecto (0 = permanente)", default=30)
    cupo = crescent.option(int, "Cupo máximo simultáneo (opcional: dejar vacío o 0 para ilimitado)", default=0)
    rol = crescent.option(hikari.Role, "Rol de Discord a asignar automáticamente (opcional)", default=None)
    rol_db_id = crescent.option(int, "ID de Rol en DB a asociar (opcional)", default=None)
    servidor = crescent.option(int, "ID de servidor RCON específico (opcional: vacío = Global)", default=None)
    facturacion = crescent.option(
        str,
        "Modalidad de cobro",
        choices=(
            ("Pago Único", "ONE_TIME"),
            ("Mensualidad Recurrente", "RECURRING"),
        ),
        default="ONE_TIME"
    )
    descripcion = crescent.option(str, "Descripción del paquete (opcional)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            max_q = self.cupo if self.cupo and self.cupo > 0 else None
            role_id = str(self.rol.id) if self.rol else None
            res = await plugin.model.api.create_membership_type(
                code=self.codigo,
                name=self.nombre,
                description=self.descripcion,
                price_usd=self.precio,
                billing_type=str(self.facturacion),
                default_days=self.dias,
                max_quota=max_q,
                discord_role_id=role_id,
                role_id=self.rol_db_id,
                server_id=self.servidor
            )
            msg = res.message
            await ctx.respond(f"✅ {msg}")
        except Exception as e:
            await ctx.respond(f"❌ Error al crear tipo de membresía: {e}")


@plugin.include
@crescent.hook(admin_only)
@membership_type_group.child
@crescent.command(name="edit", description="Edita los parámetros de un paquete o tipo de membresía existente")
class DbMembershipTypeEdit:
    tipo_id = crescent.option(int, "ID numérico del tipo de membresía a editar")
    nombre = crescent.option(str, "Nuevo nombre comercial (opcional)", default=None)
    precio = crescent.option(float, "Nuevo precio en USD (opcional)", default=None)
    dias = crescent.option(int, "Nuevos días por defecto (0 = permanente, opcional)", default=None)
    cupo = crescent.option(int, "Nuevo cupo máximo (0 para ilimitado, opcional)", default=None)
    rol = crescent.option(hikari.Role, "Nuevo rol de Discord a vincular (opcional)", default=None)
    rol_db_id = crescent.option(int, "Nuevo ID de Rol en DB a asociar (opcional)", default=None)
    servidor = crescent.option(int, "Nuevo ID de servidor RCON (opcional)", default=None)
    facturacion = crescent.option(
        str,
        "Nueva modalidad de cobro (opcional)",
        choices=(
            ("Pago Único", "ONE_TIME"),
            ("Mensualidad Recurrente", "RECURRING"),
        ),
        default=None
    )
    activo = crescent.option(bool, "¿Activar o desactivar este paquete? (opcional)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            kwargs = {}
            if self.nombre is not None:
                kwargs["name"] = self.nombre
            if self.precio is not None:
                kwargs["price_usd"] = self.precio
            if self.dias is not None:
                kwargs["default_days"] = self.dias
            if self.cupo is not None:
                kwargs["max_quota"] = self.cupo if self.cupo > 0 else None
            if self.rol is not None:
                kwargs["discord_role_id"] = str(self.rol.id)
            if self.rol_db_id is not None:
                kwargs["role_id"] = self.rol_db_id
            if self.servidor is not None:
                kwargs["server_id"] = self.servidor
            if self.facturacion is not None:
                kwargs["billing_type"] = str(self.facturacion)
            if self.activo is not None:
                kwargs["is_active"] = self.activo

            if not kwargs:
                await ctx.respond("⚠️ No especificaste ningún campo para actualizar.")
                return

            res = await plugin.model.api.update_membership_type(self.tipo_id, **kwargs)
            msg = res.message
            await ctx.respond(f"✅ {msg}")
        except Exception as e:
            await ctx.respond(f"❌ Error al actualizar tipo de membresía: {e}")
