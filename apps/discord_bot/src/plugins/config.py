import asyncio
import logging

import crescent
import hikari

from src.groups import config_group, role_group, roles_group, whitelist_group
from src.hooks import admin_only
from src.model import Model
from src.trace import get_tracer

logger = logging.getLogger(__name__)

plugin = crescent.Plugin[hikari.GatewayBot, Model]()

@plugin.include
@crescent.hook(admin_only)
@config_group.child
@crescent.command(name="announcement_channel", description="Configura el canal de anuncios (Admin)")
class ConfigChannel:
    channel = crescent.option(hikari.TextableGuildChannel, "El canal donde enviar anuncios de RCON")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        await plugin.model.api.set_bot_config("ANNOUNCEMENT_CHANNEL_ID", str(self.channel.id))
        await ctx.respond(f"✅ Canal de anuncios configurado a <#{self.channel.id}>")


async def autocomplete_role_type(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    standard_types = ["SYSTEM", "VIP", "SPECIAL", "PUBLIC"]
    val = str(option.value or "").strip().upper()
    results = []
    if val and val not in standard_types:
        results.append((f"Personalizado: {val}", val))
    for t in standard_types:
        if not val or val in t:
            results.append((f"{t} (Estándar)", t))
    return results[:25]


async def autocomplete_db_roles(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    """Autocompleta roles registrados en la Base de Datos (DDD)."""
    val = str(option.value or "").strip().lower()
    try:
        roles = await plugin.model.api.get_all_roles()
        results = []
        for r in roles:
            code = r.get("code", "")
            name = r.get("name", code)
            rtype = r.get("role_type", "")
            label = f"{name} ({code}) [{rtype}]"[:100]
            if not val or val in code.lower() or val in name.lower() or val in rtype.lower():
                results.append((label, code))
        return results[:25]
    except Exception:
        return []


@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="register", description="Registra o actualiza un rol en la Base de Datos (DDD)")
class RegisterRole:
    code = crescent.option(str, "Código único del Rol (ej. VIP_EXPRESS, MASTERCHEF)")
    name = crescent.option(str, "Nombre descriptivo del Rol")
    role_type = crescent.option(str, "Tipo de rol (estándar o personalizado)", autocomplete=autocomplete_role_type)
    discord_role = crescent.option(hikari.Role, "Rol de Discord a asociar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            norm_type = self.role_type.strip().upper()
            await plugin.model.api.register_role(
                code=self.code.upper(),
                name=self.name,
                role_type=norm_type,
                discord_role_id=str(self.discord_role.id)
            )
            await ctx.respond(f"✅ Rol `{self.code.upper()}` registrado como `{norm_type}` y asociado a <@&{self.discord_role.id}>.")
        except Exception as e:
            await ctx.respond(f"❌ Error al registrar rol: {e}")

@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="list", description="Lista todos los roles registrados en la Base de Datos")
class ListRoles:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            roles = await plugin.model.api.get_all_roles()
            if not roles:
                await ctx.respond("No hay roles registrados.")
                return
            
            msg = "**Roles Registrados (DDD):**\n"
            for r in roles:
                msg += f"- `{r.get('code')}` ({r.get('role_type')}): {r.get('name')} -> <@&{r.get('discord_role_id')}>\n"
            await ctx.respond(msg)
        except Exception as e:
            await ctx.respond(f"❌ Error al listar roles: {e}")

@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="player_list", description="Lista todos los jugadores que poseen un rol específico en la BD")
class ListPlayersByRole:
    rol = crescent.option(str, "Rol registrado en la Base de Datos", autocomplete=autocomplete_db_roles)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            roles = await plugin.model.api.get_all_roles()
            role_obj = next((r for r in roles if r.get("code", "").upper() == self.rol.strip().upper()), None)
            role_code = str(role_obj["code"]) if (role_obj and "code" in role_obj) else self.rol.strip().upper()
            
            players = await plugin.model.api.get_players_by_role(role_code)
            
            if not players:
                await ctx.respond(f"ℹ️ Ningún jugador tiene el rol `{role_code}`.")
                return
                
            msg = f"**Jugadores con el rol `{role_code}` ({len(players)}):**\n"
            for p in players:
                steam_id = p.get("steam_id")
                discord_id = p.get("discord_id")
                discord_str = f"<@{discord_id}>" if discord_id else "Sin Discord"
                msg += f"- `{steam_id}` | {discord_str}\n"
                
            # split message if too long
            if len(msg) > 1900:
                for i in range(0, len(msg), 1900):
                    await ctx.respond(msg[i:i+1900])
            else:
                await ctx.respond(msg)
        except Exception as e:
            await ctx.respond(f"❌ Error al listar jugadores por rol: {e}")

@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="give", description="Asigna un rol registrado en la Base de Datos a un jugador vinculado")
class GiveRole:
    usuario = crescent.option(hikari.User, "Usuario de Discord a asignar el rol")
    rol = crescent.option(str, "Rol registrado en la Base de Datos", autocomplete=autocomplete_db_roles)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no tiene cuenta vinculada.")
                return
            steam_id = player_info.steam_id
            
            roles = await plugin.model.api.get_all_roles()
            role_obj = next((r for r in roles if r.get("code", "").upper() == self.rol.strip().upper()), None)
            role_code = str(role_obj["code"]) if (role_obj and "code" in role_obj) else self.rol.strip().upper()
            
            await plugin.model.api.add_special_role(str(steam_id), role_code)
            
            discord_msg = ""
            if role_obj and role_obj.get("discord_role_id") and ctx.guild_id:
                from src.plugins.tasks import sync_single_user_roles
                sync_res = await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)
                if sync_res.get("success"):
                    discord_msg = " (y roles sincronizados en Discord)"
                else:
                    discord_msg = " (nota: error al sincronizar en Discord)"
                    
            await ctx.respond(f"✅ Rol `{role_code}` asignado a {self.usuario.mention} (`{steam_id}`){discord_msg}.")
        except Exception as e:
            await ctx.respond(f"❌ Error al asignar rol: {e}")

@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="remove", description="Remueve un rol de la Base de Datos a un jugador vinculado")
class RemoveRole:
    usuario = crescent.option(hikari.User, "Usuario de Discord a remover el rol")
    rol = crescent.option(str, "Rol registrado en la Base de Datos a remover", autocomplete=autocomplete_db_roles)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no tiene cuenta vinculada.")
                return
            steam_id = player_info.steam_id
            
            roles = await plugin.model.api.get_all_roles()
            role_obj = next((r for r in roles if r.get("code", "").upper() == self.rol.strip().upper()), None)
            role_code = str(role_obj["code"]) if (role_obj and "code" in role_obj) else self.rol.strip().upper()
            
            await plugin.model.api.remove_special_role(str(steam_id), role_code)
            
            discord_msg = ""
            if role_obj and role_obj.get("discord_role_id") and ctx.guild_id:
                from src.plugins.tasks import sync_single_user_roles
                sync_res = await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)
                if sync_res.get("success"):
                    discord_msg = " (y roles sincronizados en Discord)"
                else:
                    discord_msg = " (nota: error al sincronizar en Discord)"
                    
            await ctx.respond(f"✅ Rol `{role_code}` removido de {self.usuario.mention} (`{steam_id}`){discord_msg}.")
        except Exception as e:
            await ctx.respond(f"❌ Error al remover rol: {e}")

@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="remove_all", description="Remueve todos los roles administrados a los que un usuario está vinculado")
class RolesRemoveAll:
    usuario = crescent.option(hikari.User, "Usuario de Discord a limpiar roles")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no tiene cuenta vinculada.")
                return

            res = await plugin.model.api.sync_memberships()
            role_maps = res.get("role_maps", {})
            managed_special_roles = res.get("managed_special_roles", [])
            all_managed_roles = set(role_maps.values()).union(set(managed_special_roles))

            link_role_id = await plugin.model.api.get_bot_config("LINK_ROLE_ID")
            if link_role_id and link_role_id.isdigit():
                all_managed_roles.add(int(link_role_id))

            removed_count = 0
            if ctx.guild_id:
                member = await ctx.app.rest.fetch_member(ctx.guild_id, self.usuario.id)
                if member:
                    current_roles = set(member.role_ids)
                    for r_id in all_managed_roles:
                        if r_id in current_roles:
                            await ctx.app.rest.remove_role_from_member(ctx.guild_id, self.usuario.id, r_id)
                            removed_count += 1

            await ctx.respond(f"✅ Se han removido {removed_count} roles administrados de {self.usuario.mention}.")
        except Exception as e:
            await ctx.respond(f"❌ Error al remover roles: {e}")

@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="sync", description="Sincroniza y verifica que el usuario tenga los roles correspondientes a su vinculación")
class RolesSync:
    usuario = crescent.option(hikari.User, "Usuario de Discord a sincronizar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        tracer = get_tracer()
        try:
            with tracer.measure("Verificar vinculación en API", category="DB", action="FETCH", target=str(self.usuario.id)) as t:
                player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
                if not player_info:
                    t["status"] = "WARN"
                    t["details"] = "Usuario sin cuenta vinculada"
                    await ctx.respond(tracer.append_to_message(f"❌ El usuario {self.usuario.mention} no tiene cuenta vinculada."))
                    return
                t["details"] = f"Steam ID: {player_info.steam_id}"

            with tracer.measure("Sincronizar roles Discord", category="DISCORD", action="SYNC", target=str(self.usuario.id)) as t:
                from src.plugins.tasks import sync_single_user_roles
                res = await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)
                t["details"] = f"Modificado: +{res.get('added', 0)} / -{res.get('removed', 0)} roles"
                if not res.get("success"):
                    t["status"] = "ERROR"
                    t["error"] = res.get("error")

            if res.get("success"):
                base_msg = f"✅ Sincronización completada para {self.usuario.mention}: `{res.get('added', 0)}` roles añadidos, `{res.get('removed', 0)}` roles removidos."
            else:
                base_msg = f"❌ Error al sincronizar: {res.get('error')}"

            await ctx.respond(tracer.append_to_message(base_msg))
        except Exception as e:
            await ctx.respond(tracer.append_to_message(f"❌ Error al sincronizar roles: {e}"))

@plugin.include
@crescent.hook(admin_only)
@config_group.child
@crescent.command(name="list", description="Lista todas las configuraciones y mapeos activos")
class ListConfigs:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        configs = await plugin.model.api.get_bot_configs()
        
        if not configs:
            await ctx.respond("ℹ️ No hay configuraciones activas.")
            return
            
        embed = hikari.Embed(
            title="⚙️ Configuraciones del Bot",
            color=0x00A2E8
        )
        
        for key, value in configs.items():
            if key.startswith("ROLE_MAP_"):
                tipo = key.replace("ROLE_MAP_", "")
                embed.add_field(name=f"Mapeo de Rol: {tipo}", value=f"<@&{value}> (ID: {value})", inline=False)
            else:
                if key.endswith("_ROLE_ID") or key.endswith("_ROLE_IDS"):
                    roles = [f"<@&{r.strip()}>" for r in value.split(",")]
                    val_str = ", ".join(roles)
                else:
                    val_str = value
                embed.add_field(name=key, value=val_str, inline=False)
                
        await ctx.respond(embed=embed)

@plugin.include
@crescent.hook(admin_only)
@whitelist_group.child
@crescent.command(name="add", description="Añade un usuario a la Whitelist para que el bot no le quite roles")
class AddWhitelist:
    usuario = crescent.option(hikari.User, "Usuario de Discord a proteger")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        
        current_wl = await plugin.model.api.get_bot_config("SYNC_WHITELIST")
        wl_list = current_wl.split(",") if current_wl else []
        
        user_id_str = str(self.usuario.id)
        if user_id_str not in wl_list:
            wl_list.append(user_id_str)
            await plugin.model.api.set_bot_config("SYNC_WHITELIST", ",".join(wl_list))
            await ctx.respond(f"✅ Usuario <@{self.usuario.id}> añadido a la Whitelist de sincronización.")
        else:
            await ctx.respond(f"⚠️ El usuario <@{self.usuario.id}> ya estaba en la Whitelist.")

@plugin.include
@crescent.hook(admin_only)
@whitelist_group.child
@crescent.command(name="remove", description="Remueve un usuario de la Whitelist")
class RemoveWhitelist:
    usuario = crescent.option(hikari.User, "Usuario de Discord a desproteger")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        
        current_wl = await plugin.model.api.get_bot_config("SYNC_WHITELIST")
        wl_list = current_wl.split(",") if current_wl else []
        
        user_id_str = str(self.usuario.id)
        if user_id_str in wl_list:
            wl_list.remove(user_id_str)
            if wl_list:
                await plugin.model.api.set_bot_config("SYNC_WHITELIST", ",".join(wl_list))
            else:
                await plugin.model.api.delete_bot_config("SYNC_WHITELIST")
            await ctx.respond(f"✅ Usuario <@{self.usuario.id}> removido de la Whitelist.")
        else:
            await ctx.respond(f"⚠️ El usuario <@{self.usuario.id}> no estaba en la Whitelist.")

@plugin.include
@crescent.hook(admin_only)
@whitelist_group.child
@crescent.command(name="list", description="Lista los usuarios en la Whitelist de sincronización")
class ListWhitelist:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        current_wl = await plugin.model.api.get_bot_config("SYNC_WHITELIST")
        if not current_wl:
            await ctx.respond("ℹ️ Actualmente no hay usuarios en la Whitelist.")
            return
            
        wl_list = current_wl.split(",")
        mentions = "\n".join([f"- <@{u}>" for u in wl_list if u])
        await ctx.respond(f"🛡️ **Usuarios en Whitelist (Protegidos):**\n{mentions}")

@plugin.include
@crescent.hook(admin_only)
@config_group.child
@crescent.command(name="match_channel", description="Configura el canal donde se enviarán los resultados de las partidas")
class SetMatchChannel:
    canal = crescent.option(hikari.TextableChannel, "Canal de Discord")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        await plugin.model.api.set_bot_config("MATCH_ANNOUNCE_CHANNEL_ID", str(self.canal.id))
        await ctx.respond(f"✅ Canal de resultados configurado exitosamente a <#{self.canal.id}>.")


async def _sync_retroactive_link_role(ctx: crescent.Context, guild_id: int, role_id: int) -> tuple[int, int]:
    assigned_count = 0
    already_had_count = 0
    page = 1
    limit = 100
    try:
        while True:
            res = await plugin.model.api.get_paginated_players(page=page, limit=limit, linked="linked")
            players = res.get("players", [])
            if not players:
                break
            for p in players:
                d_id_str = p.get("discord_id")
                if not d_id_str or not d_id_str.isdigit():
                    continue
                try:
                    d_id = int(d_id_str)
                    await asyncio.sleep(0.05)
                    member = plugin.app.cache.get_member(guild_id, d_id)
                    if not member:
                        member = await plugin.app.rest.fetch_member(guild_id, d_id)
                    if member:
                        if role_id not in member.role_ids:
                            await member.add_role(role_id, reason="Rol de vinculación asignado retroactivamente (/role set_link)")
                            assigned_count += 1
                        else:
                            already_had_count += 1
                except hikari.NotFoundError:
                    continue
                except hikari.ForbiddenError as fe:
                    logger.warning(f"Permisos insuficientes para asignar rol {role_id} en guild {guild_id}: {fe}")
                    break
                except Exception as ex:
                    logger.debug(f"No se pudo asignar rol de link a {d_id_str}: {ex}")

            total = res.get("total", 0)
            if len(players) < limit or page * limit >= total:
                break
            page += 1

        summary = f"✅ Rol de vinculación configurado a <@&{role_id}>. Se otorgará automáticamente al usar `/player link`.\n🔗 **Sincronización retroactiva finalizada:** {assigned_count} rol(es) asignado(s)"
        if already_had_count > 0:
            summary += f" ({already_had_count} ya lo tenían)."
        else:
            summary += "."
        try:
            await ctx.edit(content=summary)
        except Exception as edit_err:
            logger.debug(f"No se pudo actualizar mensaje de /role set_link: {edit_err}")
    except Exception as e:
        logger.error(f"Error al sincronizar rol de vinculación retroactivo: {e}")
    return assigned_count, already_had_count


async def _execute_set_link(ctx: crescent.Context, rol: hikari.Role | None) -> asyncio.Task | None:
    await ctx.defer(ephemeral=True)
    if rol:
        if getattr(rol, "is_managed", False) is True:
            await ctx.respond("❌ No se puede asignar un rol administrado por Discord/integraciones.")
            return None

        await plugin.model.api.set_bot_config("LINK_ROLE_ID", str(rol.id))
        if ctx.guild_id:
            await plugin.model.api.set_bot_config("GUILD_ID", str(ctx.guild_id))
        
        if ctx.guild_id:
            await ctx.respond(
                f"✅ Rol de vinculación configurado a <@&{rol.id}>. Se otorgará automáticamente al usar `/player link`.\n"
                f"⏳ Sincronizando usuarios vinculados en este servidor en segundo plano..."
            )
            task = asyncio.create_task(_sync_retroactive_link_role(ctx, ctx.guild_id, rol.id))
            return task
        else:
            await ctx.respond(f"✅ Rol de vinculación configurado a <@&{rol.id}>. Se otorgará automáticamente al usar `/player link`.")
            return None
    else:
        await plugin.model.api.set_bot_config("LINK_ROLE_ID", "")
        await ctx.respond("✅ Rol de vinculación desactivado.")
        return None


@plugin.include
@crescent.hook(admin_only)
@role_group.child
@crescent.command(name="set_link", description="Configura el rol que se otorga automáticamente al vincular la cuenta")
class RoleSetLink:
    rol = crescent.option(hikari.Role, "Rol a asignar al vincular (opcional, omitir para desactivar)", default=None)

    async def callback(self, ctx: crescent.Context) -> asyncio.Task | None:
        return await _execute_set_link(ctx, self.rol)


@plugin.include
@crescent.hook(admin_only)
@roles_group.child
@crescent.command(name="set_link", description="Configura el rol que se otorga automáticamente al vincular la cuenta")
class RolesSetLink:
    rol = crescent.option(hikari.Role, "Rol a asignar al vincular (opcional, omitir para desactivar)", default=None)

    async def callback(self, ctx: crescent.Context) -> asyncio.Task | None:
        return await _execute_set_link(ctx, self.rol)





@plugin.include
@crescent.event
async def on_started(event: hikari.StartedEvent) -> None:
    try:
        guilds = list(plugin.app.cache.get_guilds_view())
        if guilds:
            existing = await plugin.model.api.get_bot_config("GUILD_ID")
            if not existing:
                await plugin.model.api.set_bot_config("GUILD_ID", str(guilds[0]))
                logger.info(f"Configurado GUILD_ID primario en BotConfig: {guilds[0]}")
    except Exception as e:
        logger.debug(f"No se pudo inicializar GUILD_ID en startup: {e}")


