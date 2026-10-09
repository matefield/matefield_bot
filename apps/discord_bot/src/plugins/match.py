import crescent
import hikari

from src.hooks import admin_only
from src.model import Model

plugin = crescent.Plugin[hikari.GatewayBot, Model]()
from src.groups import match_group, server_group


@plugin.include
@match_group.child
@match_group.child
@crescent.command(name="status", description="Muestra el estado de la partida actual")
class MatchStatus:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            status = await plugin.model.api.get_status()
            
            embed = hikari.Embed(title=f"🎮 Estado del Servidor: {status.serverName or 'Desconocido'}", color=0x2ECC71)
            embed.add_field(name="🗺️ Mapa", value=f"**{status.map or 'N/A'}**", inline=True)
            
            players = status.players
            current_players = players.current if players else 0
            max_players = players.max if players else 0
            embed.add_field(name="👥 Jugadores", value=f"**{current_players}** / {max_players}", inline=True)
            
            match_seconds = getattr(status, 'matchSeconds', 0) or 0
            if match_seconds:
                minutes = match_seconds // 60
                seconds = match_seconds % 60
                embed.add_field(name="⏱️ Tiempo", value=f"**{minutes}m {seconds}s**", inline=True)
            
            factions = status.factionScores or []
            if factions:
                factions_str = ""
                faction_emojis = {
                    "Lonestar": "🔵",
                    "Manticore": "🟢",
                    "Valkyre": "🔴",
                    "Valkyria": "🔴",
                    "Valkyrie": "🔴"
                }
                for f in factions:
                    faction_name = f.name or 'N/A'
                    emoji = faction_emojis.get(faction_name, "🏁")
                    factions_str += f"{emoji} **{faction_name}**: `{getattr(f, 'score', 0)}` pts\n"
                embed.add_field(name="🏆 Puntajes por Equipo", value=factions_str, inline=False)
                
            embed.set_footer(text="Wardogs RCON")
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar RCON: {e}")


@plugin.include
@match_group.child
@match_group.child
@crescent.command(name="players", description="Muestra todos los jugadores en la partida")
class MatchPlayers:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            status = await plugin.model.api.get_status()
            data = await plugin.model.api.get_players()
            players = data.players or []
            
            if not players:
                await ctx.respond("No hay jugadores conectados actualmente.")
                return
                
            # Build Embed 1: Status
            server_name = status.serverName or "Desconocido"
            server_id = getattr(status, "serverId", "Desconocido")
            map_name = status.map or "Desconocido"
            lighting = status.lighting or "Desconocido"
            score_cap = status.scoreCap or 100
            
            players_current = status.players.current if status.players else 0
            players_max = status.players.max if status.players else 100
            
            embed_status = hikari.Embed(
                title="Estado del servidor - 🟢 ONLINE",
                color=0x1DD65C
            )
            embed_status.description = f"📛 **Nombre:** {server_name}\n\n🔗 **ID para unirse:** {server_id}"
            
            embed_status.add_field(name="🗺️ Partida", value=f"{map_name} - {lighting}", inline=False)
            embed_status.add_field(name="👥 Jugadores", value=f"{players_current}/{players_max}", inline=True)
            
            # Calculate duration
            duration_str = "Desconocido"
            if status.matchSeconds is not None:
                m, s = divmod(status.matchSeconds, 60)
                h, m = divmod(m, 60)
                duration_str = f"{h:02d}:{m:02d}:{s:02d}"
                
            embed_status.add_field(name="⏱️ Duración del match", value=duration_str, inline=True)
            
            next_map = "Desconocido"
            if status.experiences and status.rotation and status.rotation.nextIndex is not None:
                if status.rotation.nextIndex < len(status.experiences):
                    next_map = status.experiences[status.rotation.nextIndex]
                
            embed_status.add_field(name="⏭️ Próximo mapa", value=next_map, inline=False)
            import datetime
            embed_status.set_footer(text=f"Actualizado • hoy a las {datetime.datetime.now().strftime('%H:%M')}")
            
            # Build Embed 2: Scoreboard
            embed_score = hikari.Embed(color=0x2B2D31) # Dark color
            
            factions = {"Lonestar": [], "Valkyra": [], "Manticore": []}
            for p in players:
                # Some might have 'Valkyre' or 'Valkyria', let's normalize
                fac = p.faction if p.faction else "Ninguna"
                if fac.startswith("Valk"): fac = "Valkyra"
                if fac in factions:
                    factions[fac].append(p)
                    
            # Add faction scores if available
            scores = {}
            if status.factionScores:
                for f in status.factionScores:
                    fac = f.name
                    if fac and fac.startswith("Valk"): fac = "Valkyra"
                    scores[fac] = f.score
                    
            for fname in ["Lonestar", "Valkyra", "Manticore"]:
                score = scores.get(fname, 0)
                
                p_list = sorted(factions[fname], key=lambda x: x.kills or 0, reverse=True)
                p_lines = []
                for p in p_list[:15]: # Show top 15 per faction
                    name = (p.name[:10] + "..") if p.name and len(p.name) > 12 else (p.name or "Unknown")
                    kills = p.kills or 0
                    deaths = p.deaths or 0
                    p_lines.append(f"{name:<12} {kills}/{deaths}")
                
                if len(p_list) > 15:
                    p_lines.append(f"+{len(p_list)-15} más...")
                    
                p_text = "`\n" + "\n".join(p_lines) + "\n`" if p_lines else "`\nVacío\n`"
                embed_score.add_field(name=f"{fname} - {score}/{score_cap}", value=p_text, inline=True)
                
            # Build Embed 3: Banner
            embed_banner = hikari.Embed(color=0x2B2D31)
            embed_banner.set_image("https://i.imgur.com/1G8O3v8.jpeg") # Fallback dummy image
            
            await ctx.respond(embeds=[embed_status, embed_score, embed_banner])
            
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar RCON: {e}")


@plugin.include
@match_group.child
@match_group.child
@crescent.command(name="leaderboard", description="Muestra el top 10 de jugadores en la partida")
class MatchLeaderboard:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            data = await plugin.model.api.get_players()
            players = data.players or []
            
            if not players:
                await ctx.respond("No hay jugadores conectados actualmente.")
                return
                
            # Fetch steam names
            steam_ids = [p.steamId for p in players if p.steamId is not None]
            steam_names = {}
            if steam_ids:
                steam_summaries = await plugin.model.api.get_steam_players_batch(steam_ids)
                for sid, summary in steam_summaries.items():
                    if "personaname" in summary:
                        steam_names[sid] = summary["personaname"]
            
            # Ordenar por kills de mayor a menor
            players.sort(key=lambda x: getattr(x, 'kills', 0) or 0, reverse=True)
            
            embed = hikari.Embed(title="🏆 Top 10 - Match Leaderboard", color=0xFFD700)
            
            faction_emojis = {
                "Lonestar": "🔵",
                "Manticore": "🟢",
                "Valkyre": "🔴",
                "Valkyria": "🔴",
                "Valkyrie": "🔴"
            }
            
            for i, p in enumerate(players[:10], 1): # Top 10 max
                name = steam_names.get(p.steamId, getattr(p, 'name', 'Unknown'))
                kills = getattr(p, 'kills', 0) or 0
                deaths = getattr(p, 'deaths', 0) or 0
                cash = getattr(p, 'cash', 0) or 0
                faction = getattr(p, 'faction', 'Ninguna') or 'Ninguna'
                emoji = faction_emojis.get(faction, "🏁")
                
                embed.add_field(
                    name=f"#{i} - {name} ({emoji} {faction})",
                    value=f"🔫 **Kills:** `{kills}` | ⚰️ **Deaths:** `{deaths}` | 💰 **Cash:** `${cash}` | 🆔 `{p.steamId}`",
                    inline=False
                )
                
            embed.set_footer(text=f"Total en partida: {len(players)} jugadores")
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar RCON: {e}")


@plugin.include
@match_group.child
@match_group.child
@crescent.command(name="player_info", description="[RCON] Muestra información EN VIVO de un jugador en la partida actual")
class MatchPlayer:
    steam_id = crescent.option(str, "Steam ID del jugador")
    
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            data = await plugin.model.api.get_players()
            players = data.players or []
            player_in_match = next((p for p in players if p.steamId == self.steam_id), None)
            
            if not player_in_match:
                await ctx.respond(f"❌ El jugador con Steam ID `{self.steam_id}` no está en la partida.")
                return
                
            player_name = player_in_match.name or "Desconocido"
            steam_summary = await plugin.model.api.get_steam_player(self.steam_id)
            if steam_summary and "personaname" in steam_summary:
                player_name = steam_summary["personaname"]
                
            embed = hikari.Embed(title=f"🔴 En Vivo: {player_name}", color=0xFF4500)
            
            faction = getattr(player_in_match, 'faction', 'N/A') or 'N/A'
            faction_emojis = {
                "Lonestar": "🔵",
                "Manticore": "🟢",
                "Valkyre": "🔴",
                "Valkyria": "🔴",
                "Valkyrie": "🔴"
            }
            emoji = faction_emojis.get(faction, "🏳️")
            
            embed.add_field(
                name="Estadísticas de la Partida",
                value=(
                    f"{emoji} **Facción:** `{faction}`\n"
                    f"🔫 **Kills:** `{getattr(player_in_match, 'kills', 0) or 0}`\n"
                    f"⚰️ **Deaths:** `{getattr(player_in_match, 'deaths', 0) or 0}`\n"
                    f"💰 **Cash:** `${getattr(player_in_match, 'cash', 0) or 0}`\n"
                    f"📶 **Ping:** `{getattr(player_in_match, 'pingMs', 0) or 0} ms`"
                ),
                inline=False
            )
            embed.set_footer(text=f"Steam ID: {self.steam_id}")
            
            components = [
                ctx.app.rest.build_message_action_row()
                .add_interactive_button(hikari.ButtonStyle.DANGER, f"kick_{self.steam_id}", label="🥾 Kickear")
                .add_interactive_button(hikari.ButtonStyle.DANGER, f"ban_{self.steam_id}", label="🔨 Banear")
                .add_interactive_button(hikari.ButtonStyle.SECONDARY, f"faction_{self.steam_id}", label="🔄 Cambiar Facción")
            ]
            
            await ctx.respond(embed=embed, components=components)
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar estadísticas en vivo: {e}")


@plugin.include
@crescent.hook(admin_only)
@server_group.child
@crescent.command(name="logs", description="Muestra los últimos 10 logs de auditoría (ADMIN)")
class ServerLogs:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            data = await plugin.model.api.get_audit_logs(limit=10)
            entries = data.entries or []
            
            if not entries:
                await ctx.respond("No hay logs disponibles.")
                return
                
            embed = hikari.Embed(title="📜 Últimos Logs de Auditoría", color=0x95A5A6)
            
            for log in entries:
                time = log.timestampUtc or "Desconocido"
                event = log.event or "Evento"
                detail = log.detail or "Sin detalles"
                
                # Format time string nicely if it's ISO format
                if "T" in time:
                    time = time.replace("T", " ")[:19]
                    
                embed.add_field(name=f"[{time}] {event}", value=f"`{detail}`", inline=False)
                
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al consultar RCON: {e}")

@plugin.include
@crescent.event
async def on_interaction(event: hikari.InteractionCreateEvent) -> None:
    if isinstance(event.interaction, hikari.ModalInteraction):
        custom_id = event.interaction.custom_id
        if custom_id.startswith("modal_ban_"):
            steam_id = custom_id.replace("modal_ban_", "")
            reason = event.interaction.components[0].components[0].value
            
            await event.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
            try:
                await plugin.model.api.ban_player(steam_id, reason)
                await event.interaction.edit_initial_response(content=f"🔨 Jugador `{steam_id}` baneado exitosamente. Motivo: {reason}", components=[])
            except Exception as e:
                await event.interaction.edit_initial_response(content=f"❌ Error al banear: {e}")
                
        elif custom_id.startswith("modal_faction_"):
            steam_id = custom_id.replace("modal_faction_", "")
            faction = event.interaction.components[0].components[0].value
            
            await event.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
            try:
                await plugin.model.api.switch_faction(steam_id, faction)
                await event.interaction.edit_initial_response(content=f"🔄 Jugador `{steam_id}` movido a la facción `{faction}` exitosamente.", components=[])
            except Exception as e:
                await event.interaction.edit_initial_response(content=f"❌ Error al cambiar facción: {e}")
        return

    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return
        
    custom_id = event.interaction.custom_id
    if custom_id.startswith("kick_"):
        steam_id = custom_id.replace("kick_", "")
        await event.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        try:
            await plugin.model.api.kick_player(steam_id, "Expulsado por Administrador")
            await event.interaction.edit_initial_response(content=f"🥾 Jugador `{steam_id}` expulsado exitosamente.", components=[])
        except Exception as e:
            await event.interaction.edit_initial_response(content=f"❌ Error al expulsar: {e}")
            
    elif custom_id.startswith("ban_"):
        steam_id = custom_id.replace("ban_", "")
        
        # Build modal to ask for reason
        await event.interaction.create_modal_response(
            "Banear Jugador",
            f"modal_ban_{steam_id}",
            components=[
                plugin.app.rest.build_modal_action_row()
                .add_text_input("reason", "Motivo del Ban", style=hikari.TextInputStyle.PARAGRAPH, required=True, placeholder="Razón...")
            ]
        )
        
    elif custom_id.startswith("faction_"):
        steam_id = custom_id.replace("faction_", "")
        
        # Build modal to ask for faction
        await event.interaction.create_modal_response(
            "Cambiar Facción",
            f"modal_faction_{steam_id}",
            components=[
                plugin.app.rest.build_modal_action_row()
                .add_text_input("faction", "Nombre/ID de Facción", style=hikari.TextInputStyle.SHORT, required=True, placeholder="ej. Lonestar")
            ]
        )
