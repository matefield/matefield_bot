import logging

import crescent
import hikari

logger = logging.getLogger(__name__)
from src.hooks import admin_only
from src.model import Model

plugin = crescent.Plugin[hikari.GatewayBot, Model]()
from src.groups import leaderboard_group, player_group, server_group, special_role_group


@plugin.include
@leaderboard_group.child
@crescent.command(name="list", description="Muestra el Top 15 de jugadores")
class DbLeaderboard:
    metric = crescent.option(
        str, 
        "Métrica a usar para el ranking", 
        choices=(
            ("Kills", "kills"),
            ("Muertes", "deaths"),
            ("Dinero Generado", "cash_earned")
        ),
        default="kills"
    )

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        
        try:            res = await plugin.model.api.get_leaderboard(metric=str(self.metric), limit=15)
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar la base de datos: {e}")
            return
            
        leaderboard = res.get("leaderboard", [])
        
        if not leaderboard:
            await ctx.respond("⚠️ No hay datos suficientes para mostrar el leaderboard.")
            return

        embed = hikari.Embed(
            title=f"🏆 Top 15 Jugadores - {str(self.metric).replace('_', ' ').title()}",
            color=0xFFD700
        )
        
        steam_ids = [entry['steam_id'] for entry in leaderboard if 'steam_id' in entry]
        steam_names = {}
        if steam_ids:
            steam_names = await plugin.model.api.get_steam_players_batch(steam_ids)
            
        description = ""
        for i, entry in enumerate(leaderboard, 1):
            steam_id = entry['steam_id']
            discord_id = entry.get("discord_id")
            s_data = steam_names.get(steam_id, {})
            steam_name = s_data.get("personaname") or s_data.get("name") or f"SteamID: {steam_id}"
            
            player_mention = steam_name
            if discord_id:
                try:
                    user = None
                    if hasattr(ctx.app, "cache"):
                        user = ctx.app.cache.get_user(int(discord_id)) # type: ignore
                    if not user:
                        user = await ctx.app.rest.fetch_user(int(discord_id))
                    player_mention = f"@{user.username}"
                except Exception:
                    player_mention = f"<@{discord_id}>"
            
            description += f"**{i}.** {player_mention} - **{entry['total']}**\n"
            
        embed.description = description
        await ctx.respond(embed=embed)




@plugin.include
@player_group.child
@crescent.command(name="list", description="Lista todos los jugadores registrados (Paginado)")
class DbPlayers:
    vinculacion = crescent.option(str, "Filtrar por vinculación a Discord", choices=(("Todos", "all"), ("Vinculados", "linked"), ("No Vinculados", "unlinked")), default="all")
    
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        page = 1
        try:
            res = await plugin.model.api.get_paginated_players(page=page, limit=10, linked=str(self.vinculacion))
            players = res.get("players", [])
            total = res.get("total", 0)
            
            if not players:
                await ctx.respond("No hay jugadores que coincidan con los filtros.")
                return
                
            embed = hikari.Embed(
                title=f"👥 Lista de Jugadores (Pág {page})",
                description=f"Total resultados: {total} | Filtros: Link={self.vinculacion}",
                color=0x00BFFF
            )
            
            for p in players:
                link_emoji = "🔗" if p.get('discord_id') else "❌"
                discord_str = f"<@{p['discord_id']}>" if p.get('discord_id') else "No Vinculado"
                name = p.get('name', 'Unknown')
                vip_memberships = p.get('active_memberships') or ([p.get('vip_type')] if p.get('vip_type') else [])
                vip_str = f" | **VIP:** {', '.join(vip_memberships)}" if vip_memberships else ""
                sp_str = f" | **Especial:** {p.get('special_role')}" if p.get('special_role') else ""
                
                embed.add_field(
                    name=f"{link_emoji} {name} (SteamID: {p['steam_id']})", 
                    value=f"Discord: {discord_str}{vip_str}{sp_str}", 
                    inline=False
                )
                
            l_char = str(self.vinculacion)[0:2]
            
            # Create a SelectMenu with players
            select_menu = ctx.app.rest.build_message_action_row().add_text_menu("db_players_select")
            select_menu.set_placeholder("Selecciona un jugador para ver su histórico")
            for p in players:
                name = p.get('name', 'Unknown')
                if not name: name = 'Unknown'
                # Discord limits options to 100 chars, so truncate
                label = f"{name} ({p['steam_id']})"[:100]
                select_menu.add_option(label, p['steam_id'], description=f"Ver perfil histórico de {name}"[:100])
            select_menu = select_menu.parent
            
            # Create navigation buttons
            button_row = ctx.app.rest.build_message_action_row()
            button_row.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"prev_players_{page}_{l_char}", label="⬅️ Anterior")
            button_row.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"next_players_{page}_{l_char}", label="Siguiente ➡️")
            
            components = [select_menu, button_row]
            await ctx.respond(embed=embed, components=components)
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")

class DbMatches:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        page = 1
        try:
            res = await plugin.model.api.get_paginated_matches(page=page, limit=10)
            matches = res.get("matches", [])
            total = res.get("total", 0)
            
            if not matches:
                await ctx.respond("No hay partidas registradas.")
                return
                
            embed = hikari.Embed(
                title=f"⚔️ Historial de Partidas (Pág {page})",
                description=f"Total jugadas: {total}",
                color=0xFF4500
            )
            
            for m in matches:
                start = m['start_time'][:16].replace("T", " ")
                end = m['end_time'][:16].replace("T", " ") if m['end_time'] else "En progreso"
                embed.add_field(name=f"Match ID: {m['id']}", value=f"**Mapa:** {m['map']}\n**Inicio:** {start}\n**Fin:** {end}", inline=False)
                
            components = [
                ctx.app.rest.build_message_action_row()
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"prev_matches_{page}", label="◀ Anterior")
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"next_matches_{page}", label="Siguiente ▶")
            ]
            await ctx.respond(embed=embed, components=components)
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")

@plugin.include
@crescent.event
async def on_interaction(event: hikari.InteractionCreateEvent) -> None:
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return
        
    custom_id = event.interaction.custom_id
    if custom_id.startswith("prev_players_") or custom_id.startswith("next_players_"):
        parts = custom_id.split("_")
        action = parts[0]
        current_page = int(parts[2])
        
        l_char = parts[3] if len(parts) > 3 else "al"
        
        linked = {"al": "all", "li": "linked", "un": "unlinked"}.get(l_char, "all")
        
        new_page = current_page - 1 if action == "prev" else current_page + 1
        new_page = max(new_page, 1)
            
        try:
            res = await plugin.model.api.get_paginated_players(page=new_page, limit=10, linked=linked)
            players = res.get("players", [])
            total = res.get("total", 0)
            
            if not players and action == "next":
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE
                )
                return
                
            embed = hikari.Embed(
                title=f"👥 Lista de Jugadores (Pág {new_page})",
                description=f"Total resultados: {total} | Filtros: Link={linked}",
                color=0x00BFFF
            )
            
            for p in players:
                name = p.get('name', 'Sin Nickname')
                link_emoji = "🔗" if p.get('is_linked') else "❓"
                discord_str = f"<@{p['discord_id']}>" if p.get('is_linked') else "No enlazado"
                vip_str = f" | **VIP:** {p.get('vip_type')}" if p.get('vip_type') else ""
                sp_str = f" | **Especial:** {p.get('special_role')}" if p.get('special_role') else ""
                
                embed.add_field(
                    name=f"{link_emoji} {name} (SteamID: {p['steam_id']})", 
                    value=f"Discord: {discord_str}{vip_str}{sp_str}", 
                    inline=False
                )
                
            # Create a SelectMenu with players
            select_menu = plugin.app.rest.build_message_action_row().add_text_menu("db_players_select")
            select_menu.set_placeholder("Selecciona un jugador para ver su histórico")
            for p in players:
                name = p.get('name', 'Unknown')
                if not name: name = 'Unknown'
                label = f"{name} ({p['steam_id']})"[:100]
                select_menu.add_option(label, p['steam_id'], description=f"Ver perfil histórico de {name}"[:100])
            select_menu = select_menu.parent
            
            button_row = plugin.app.rest.build_message_action_row()
            button_row.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"prev_players_{new_page}_{l_char}", label="⬅️ Anterior")
            button_row.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"next_players_{new_page}_{l_char}", label="Siguiente ➡️")
            
            components = [select_menu, button_row]
            
            await event.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                embed=embed,
                components=components
            )
        except Exception as e:
            logger.warning(f"[DB Interactions] Error al paginar jugadores ({custom_id}): {e}")

    elif custom_id == "db_players_select":
        steam_id = event.interaction.values[0]
        try:
            steam_info = await plugin.model.api.get_steam_player(steam_id)
            player_name = steam_info.get("personaname") if steam_info else "Desconocido"
            
            hist_stats = await plugin.model.api.get_player_historical_stats(steam_id)
            if not hist_stats:
                hist_stats = {"total_kills": 0, "total_deaths": 0, "total_cash_earned": 0}
                
            embed = hikari.Embed(title=f"📊 Perfil Histórico: {player_name}", color=0x3498DB)
            if steam_info and steam_info.get("avatarfull"):
                embed.set_thumbnail(steam_info["avatarfull"])
                
            embed.add_field(
                name="📚 Histórico Total",
                value=(
                    f"💀 **Kills:** `{hist_stats.get('total_kills', 0)}`\n"
                    f"⚰️ **Deaths:** `{hist_stats.get('total_deaths', 0)}`\n"
                    f"💰 **Cash Earned:** `${hist_stats.get('total_cash_earned', 0)}`"
                ),
                inline=False
            )
            embed.set_footer(text=f"Steam ID: {steam_id}")
            
            await event.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                embed=embed,
                flags=hikari.MessageFlag.EPHEMERAL # Show ephemeral to not clutter chat
            )
        except Exception as e:
            logger.warning(f"[DB Interactions] Error al obtener histórico de jugador ({custom_id}): {e}")

    elif custom_id.startswith("prev_matches_") or custom_id.startswith("next_matches_"):
        parts = custom_id.split("_")
        action = parts[0]
        current_page = int(parts[2])
        
        new_page = current_page - 1 if action == "prev" else current_page + 1
        new_page = max(new_page, 1)
            
        try:
            res = await plugin.model.api.get_paginated_matches(page=new_page, limit=10)
            matches = res.get("matches", [])
            total = res.get("total", 0)
            
            if not matches and action == "next":
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE
                )
                return
                
            embed = hikari.Embed(
                title=f"⚔️ Historial de Partidas (Pág {new_page})",
                description=f"Total jugadas: {total}",
                color=0xFF4500
            )
            
            for m in matches:
                start = m['start_time'][:16].replace("T", " ")
                end = m['end_time'][:16].replace("T", " ") if m['end_time'] else "En progreso"
                embed.add_field(name=f"Match ID: {m['id']}", value=f"**Mapa:** {m['map']}\n**Inicio:** {start}\n**Fin:** {end}", inline=False)
                
            components = [
                plugin.app.rest.build_message_action_row()
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"prev_matches_{new_page}", label="◀ Anterior")
                .add_interactive_button(hikari.ButtonStyle.PRIMARY, f"next_matches_{new_page}", label="Siguiente ▶")
            ]
            
            await event.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                embed=embed,
                components=components
            )
        except Exception as e:
            logger.warning(f"[DB Interactions] Error al paginar partidas ({custom_id}): {e}")

@plugin.include
@server_group.child
@crescent.command(name="status", description="Muestra el estado actual del servidor RCON y rotación")
class DbStatus:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            status = await plugin.model.api.get_status()
            
            embed = hikari.Embed(
                title=f"🎮 {status.serverName or 'Servidor Wardogs'}",
                color=0x32CD32
            )
            
            score_curr = status.scoreTick.current if status.scoreTick else 0
            score_max = status.scoreCap or 100
            
            embed.add_field(name="Mapa Actual", value=f"**{status.map}**", inline=True)
            embed.add_field(name="Modos", value=", ".join(status.experiences or []), inline=True)
            embed.add_field(name="Score", value=f"{score_curr} / {score_max}", inline=True)
            
            players_curr = status.players.current if status.players else 0
            players_max = status.players.max if status.players else 64
            embed.add_field(name="Jugadores", value=f"{players_curr} / {players_max}", inline=False)
            
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al conectar con el servidor: {e}")




async def autocomplete_special_roles(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    """Autocompleta únicamente roles registrados bajo la categoría SPECIAL en la DB."""
    val = str(option.value or "").strip().lower()
    try:
        roles = await plugin.model.api.get_all_roles()
        special_roles = [r for r in roles if str(r.get("role_type", "")).upper() == "SPECIAL"]
        results = []
        for r in special_roles:
            code = r.get("code", "")
            name = r.get("name", code)
            label = f"{name} ({code})"[:100]
            if not val or val in code.lower() or val in name.lower():
                results.append((label, code))
        return results[:25]
    except Exception:
        return []

async def autocomplete_all_db_roles(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    """Autocompleta cualquier rol registrado en la Base de Datos (DDD)."""
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
@special_role_group.child
@crescent.command(name="add", description="Añade un rol de tipo SPECIAL registrado en la DB a un jugador")
class DbAddSpecialRole:
    usuario = crescent.option(hikari.User, "Usuario de Discord") 
    rol_especial = crescent.option(str, "Rol de tipo SPECIAL registrado en la DB", autocomplete=autocomplete_special_roles) 

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no está vinculado.")
                return
            steam_id = player_info.steam_id

            roles = await plugin.model.api.get_all_roles()
            role_obj = next((r for r in roles if r.get("code", "").upper() == self.rol_especial.strip().upper()), None)
            if not role_obj or str(role_obj.get("role_type", "")).upper() != "SPECIAL":
                await ctx.respond("❌ Debes seleccionar un rol registrado con categoría `SPECIAL` en la DB. Para otros roles usa `/roles give` o `/player set_role`.")
                return

            role_code = str(role_obj["code"])
            await plugin.model.api.add_special_role(str(steam_id), role_code)

            from src.plugins.tasks import sync_single_user_roles
            await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)

            await ctx.respond(f"✅ Rol especial `{role_obj['name']}` (`{role_code}`) añadido al jugador {self.usuario.mention} (`{steam_id}`).")
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")

@plugin.include
@crescent.hook(admin_only)
@special_role_group.child
@crescent.command(name="remove", description="Remueve un rol de tipo SPECIAL de un jugador vinculado")
class DbRemoveSpecialRole:
    usuario = crescent.option(hikari.User, "Usuario de Discord") 
    rol_especial = crescent.option(str, "Rol de tipo SPECIAL registrado en la DB", autocomplete=autocomplete_special_roles) 

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no está vinculado.")
                return
            steam_id = player_info.steam_id

            roles = await plugin.model.api.get_all_roles()
            role_obj = next((r for r in roles if r.get("code", "").upper() == self.rol_especial.strip().upper()), None)
            role_code = str(role_obj["code"]) if (role_obj and "code" in role_obj) else self.rol_especial.strip().upper()
            await plugin.model.api.remove_special_role(str(steam_id), role_code)

            from src.plugins.tasks import sync_single_user_roles
            await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)

            await ctx.respond(f"✅ Rol especial `{role_code}` removido del jugador {self.usuario.mention} (`{steam_id}`).")
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")

@plugin.include
@crescent.hook(admin_only)
@player_group.child
@crescent.command(name="set_role", description="Asigna un rol registrado en la Base de Datos a un jugador vinculado")
class PlayerSetRole:
    usuario = crescent.option(hikari.User, "Usuario de Discord (jugador vinculado)")
    rol = crescent.option(str, "Rol registrado en la DB a asignar", autocomplete=autocomplete_all_db_roles)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no está vinculado.")
                return
            steam_id = player_info.steam_id

            roles = await plugin.model.api.get_all_roles()
            role_obj = next((r for r in roles if r.get("code", "").upper() == self.rol.strip().upper()), None)
            role_code = str(role_obj["code"]) if (role_obj and "code" in role_obj) else self.rol.strip().upper()
            await plugin.model.api.add_special_role(str(steam_id), role_code)

            from src.plugins.tasks import sync_single_user_roles
            await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)

            await ctx.respond(f"✅ Rol `{role_code}` asignado a {self.usuario.mention} (`{steam_id}`).")
        except Exception as e:
            await ctx.respond(f"❌ Error al asignar rol: {e}")

@plugin.include
@crescent.hook(admin_only)
@player_group.child
@crescent.command(name="remove_role", description="Remueve un rol de la Base de Datos de un jugador vinculado")
class PlayerRemoveRole:
    usuario = crescent.option(hikari.User, "Usuario de Discord (jugador vinculado)")
    rol = crescent.option(str, "Rol registrado en la DB a remover", autocomplete=autocomplete_all_db_roles)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no está vinculado.")
                return
            steam_id = player_info.steam_id

            roles = await plugin.model.api.get_all_roles()
            role_obj = next((r for r in roles if r.get("code", "").upper() == self.rol.strip().upper()), None)
            role_code = str(role_obj["code"]) if (role_obj and "code" in role_obj) else self.rol.strip().upper()
            await plugin.model.api.remove_special_role(str(steam_id), role_code)

            from src.plugins.tasks import sync_single_user_roles
            await sync_single_user_roles(ctx.app, plugin.model, self.usuario.id, ctx.guild_id)

            await ctx.respond(f"✅ Rol `{role_code}` removido de {self.usuario.mention} (`{steam_id}`).")
        except Exception as e:
            await ctx.respond(f"❌ Error al remover rol: {e}")

@plugin.include
@crescent.hook(admin_only)
@player_group.child
@crescent.command(name="edit", description="Edita información de un jugador (debe estar vinculado)")
class DbEditPlayer:
    usuario_discord = crescent.option(hikari.User, "Usuario de Discord (jugador vinculado)") 
    mensaje_bienvenida = crescent.option(str, "Nuevo mensaje de bienvenida personalizado", default=None) 
    observacion = crescent.option(str, "Añadir/editar nota interna sobre pagos, conducta, etc.", default=None) 

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            player_info = await plugin.model.api.get_player_by_discord(str(self.usuario_discord.id))
            if not player_info:
                await ctx.respond(f"❌ El usuario {self.usuario_discord.mention} no está vinculado a ningún Steam ID. Usa `/player link` primero.")
                return
                
            steam_id = player_info.steam_id
            
            await plugin.model.api.edit_player(
                str(steam_id), 
                custom_welcome_message=str(self.mensaje_bienvenida) if self.mensaje_bienvenida else None, 
                observations=str(self.observacion) if self.observacion else None
            )
            await ctx.respond(f"✅ Jugador `{steam_id}` ({self.usuario_discord.mention}) actualizado exitosamente.")
        except Exception as e:
            await ctx.respond(f"❌ Error: {e}")





