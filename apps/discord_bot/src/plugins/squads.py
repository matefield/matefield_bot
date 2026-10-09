import logging

import crescent
import hikari

from src.groups import squad_admin_group, squad_group
from src.model import Model

logger = logging.getLogger(__name__)

plugin = crescent.Plugin[hikari.GatewayBot, Model]()

from wardogs_schemas.v1 import SquadData

from src.ui_utils import UIColors, format_api_error


def get_medal(index: int) -> str:
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    return medals.get(index, f"**{index+1}.**")

async def resolve_target_squad(ctx: crescent.Context, steam_id: str, unidad_tag: str | None = None) -> SquadData:
    squads = await plugin.model.api.get_player_squads(steam_id)
    if not squads:
        raise Exception("No perteneces a ningún pelotón.")
    if unidad_tag:
        for sq in squads:
            if sq.tag.upper() == unidad_tag.upper():
                return sq
        raise Exception(f"No perteneces a un pelotón con el tag '{unidad_tag}'.")
    if len(squads) > 1:
        raise Exception("Perteneces a más de un pelotón. Usa el parámetro 'unidad' para especificar cuál.")
    return squads[0]

async def squad_autocomplete(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    try:
        player = await plugin.model.api.get_player_by_discord(str(ctx.user.id))
        steam_id = player.steam_id if player else None
        if not steam_id:
            return []
        squads = await plugin.model.api.get_player_squads(steam_id)
        val = str(option.value or "").strip().lower()
        results = []
        for sq in squads:
            label = f"[{sq.tag}] {sq.name}"
            if not val or val in label.lower() or val in sq.tag.lower():
                results.append((label, sq.tag))
        return results[:25]
    except Exception:
        return []

async def get_steam_id_from_member(member: hikari.Member | None, ctx: crescent.Context) -> str:
    if not member:
        await ctx.respond("❌ Este comando solo se puede usar en el servidor.", ephemeral=True)
        return ""
    try:
        player = await plugin.model.api.get_player_by_discord(str(member.id))
        return player.steam_id if player and player.steam_id else ""
    except Exception:
        await ctx.respond("❌ No estás vinculado a una cuenta de Steam. Usa `/player link` primero.", ephemeral=True)
        return ""

@plugin.include
@squad_group.child
@crescent.command(name="create_squad", description="Crea tu propio pelotón (Solo 1 por jugador)")
class SquadCreate:
    name = crescent.option(str, "Nombre completo del pelotón")
    tag = crescent.option(str, "Etiqueta corta (Ej: MATE) - Máx 4 letras")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        if len(self.tag) > 4:
            await ctx.respond("❌ El tag no puede tener más de 4 caracteres.")
            return

        try:
            res = await plugin.model.api.create_squad(self.name, self.tag, steam_id)
            embed = hikari.Embed(
                title=f"✅ Pelotón [{res.tag}] {res.name} Creado",
                description="Ya eres el líder. Usa `/squad invite_member` para reclutar a tus amigos.",
                color=UIColors.GREEN
            )
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al crear pelotón: {format_api_error(e)}")

@plugin.include
@squad_group.child
@crescent.command(name="members", description="Lista los miembros de tu pelotón o de otro especificando el tag")
class SquadMembers:
    unidad = crescent.option(str, "Tag del pelotón (opcional)", default=None, autocomplete=squad_autocomplete)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            if self.unidad:
                squad = await plugin.model.api.get_squad_by_tag(str(self.unidad))
            else:
                steam_id = await get_steam_id_from_member(ctx.member, ctx)
                if not steam_id:
                    return
                squad = await resolve_target_squad(ctx, steam_id, str(self.unidad) if self.unidad else None)
                
            members = await plugin.model.api.get_squad_members(squad.id)
            desc = f"**Líder:** {squad.leader_steam_id}\n\n"
            for i, mem in enumerate(members):
                desc += f"{i+1}. **{mem.in_game_name or 'Unknown'}** (Steam: {mem.steam_id})\n"
                
            embed = hikari.Embed(title=f"👥 Miembros de [{squad.tag}] {squad.name}", description=desc, color=UIColors.BLUE)
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al obtener miembros: {format_api_error(e)}")

@plugin.include
@squad_group.child
@crescent.command(name="view_info", description="Mira la información de tu pelotón")
class SquadInfo:
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None, autocomplete=squad_autocomplete)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, str(self.unidad) if self.unidad else None)
            
            embed = hikari.Embed(
                title=f"🛡️ [{squad.tag}] {squad.name}",
                color=UIColors.BLUE
            )
            
            stats = f"**Kills:** {squad.total_kills} ⚔️\n"
            stats += f"**Muertes:** {squad.total_deaths} 💀\n"
            stats += f"**Dinero Generado:** ${squad.total_cash_earned:,} 💸\n"
            
            # K/D Ratio
            deaths = squad.total_deaths if squad.total_deaths > 0 else 1
            kd = squad.total_kills / deaths
            stats += f"**K/D Global:** {kd:.2f} 📈"

            embed.add_field(name="Estadísticas de Pelotón", value=stats, inline=False)
            embed.set_footer(text=f"Squad ID: {squad.id} | Líder ID: {squad.leader_steam_id}")
            
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ No tienes pelotón activo o ocurrió un error: {format_api_error(e)}")

@plugin.include
@squad_group.child
@crescent.command(name="leave_squad", description="Sal del pelotón en el que estás")
class SquadLeave:
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None, autocomplete=squad_autocomplete)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, str(self.unidad) if self.unidad else None)
            await plugin.model.api.remove_squad_member(squad.id, steam_id)
            await ctx.respond(f"✅ Has abandonado el pelotón **{squad.name}**.")
        except Exception as e:
            await ctx.respond(f"❌ Error al salir del pelotón: {format_api_error(e)}")

@plugin.include
@squad_group.child
@crescent.command(name="disband", description="Disuelve tu pelotón (Solo para el Líder)")
class SquadDisband:
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None, autocomplete=squad_autocomplete)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, str(self.unidad) if self.unidad else None)
            if str(squad.leader_steam_id) != str(steam_id):
                await ctx.respond("❌ Solo el líder del pelotón puede disolverlo. Usa `/squad leave_squad` en su lugar.")
                return
                
            await plugin.model.api.disband_squad(squad.id)
            await ctx.respond(f"✅ Pelotón **{squad.name}** disuelto permanentemente.")
        except Exception as e:
            await ctx.respond(f"❌ Error al disolver: {format_api_error(e)}")

@plugin.include
@squad_group.child
@crescent.command(name="leaderboard", description="Muestra el top de pelotones del servidor")
class SquadLeaderboard:
    sort_by = crescent.option(
        str, "Ordenar por estadística", 
        choices=[
            ("Kills", "kills"),
            ("Muertes", "deaths"),
            ("Dinero Ganado", "cash"),
            ("Partidas Jugadas", "matches")
        ],
        default="kills"
    )

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            squads = await plugin.model.api.get_squad_leaderboard(str(self.sort_by))
            if not squads:
                await ctx.respond("Aún no hay pelotones registrados.")
                return
                
            desc = ""
            for i, sq in enumerate(squads):
                kd = sq.total_kills / (sq.total_deaths if sq.total_deaths > 0 else 1)
                medal = get_medal(i)
                desc += f"{medal} **[{sq.tag}] {sq.name}**\n"
                desc += f"└ ⚔️ {sq.total_kills} Kills | 💀 {sq.total_deaths} Muertes | 💸 ${sq.total_cash_earned:,} | 📈 KD: {kd:.2f} | 🎮 {sq.total_matches_played} Partidas\n\n"
                
            embed = hikari.Embed(title=f"🏆 Top Pelotones (Por {str(self.sort_by).capitalize()})", description=desc, color=UIColors.GOLD)
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al cargar leaderboard: {format_api_error(e)}")

@plugin.include
@squad_group.child
@crescent.command(name="invite_member", description="Invita a un jugador a tu pelotón")
class SquadInviteMember:
    usuario = crescent.option(hikari.User, "Usuario a invitar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        if not ctx.member or self.usuario.id == ctx.member.id:
            await ctx.respond("❌ No puedes invitarte a ti mismo (o estás en un canal inválido).")
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id)
            if str(squad.leader_steam_id) != str(steam_id):
                await ctx.respond("❌ Solo el líder del pelotón puede invitar jugadores.")
                return

            # Check if target is linked
            target_player = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not target_player or not target_player.steam_id:
                await ctx.respond(f"❌ {self.usuario.mention} no está vinculado a Steam.")
                return

            # Target is valid. Create interactive components for DM.
            squad_id = squad.id
            components = [
                plugin.app.rest.build_message_action_row()
                .add_interactive_button(hikari.ButtonStyle.SUCCESS, f"sq_accept_{squad_id}", label="✅ Aceptar")
                .add_interactive_button(hikari.ButtonStyle.DANGER, f"sq_reject_{squad_id}", label="❌ Rechazar")
            ]

            embed = hikari.Embed(
                title="📩 Invitación a Pelotón",
                description=f"**{ctx.user.username}** te ha invitado a unirte al pelotón **[{squad.tag}] {squad.name}**.\n\n¿Aceptas la invitación?",
                color=UIColors.BLUE
            )

            try:
                dm = await self.usuario.fetch_dm_channel()
                if not dm:
                    dm = await plugin.app.rest.create_dm_channel(self.usuario.id)
                await dm.send(embed=embed, components=components)
                await ctx.respond(f"✅ Invitación enviada a {self.usuario.mention} por MD.")
            except Exception:
                await ctx.respond(f"⚠️ No pude enviarle un MD a {self.usuario.mention}. ¿Tiene los MDs cerrados?")

        except Exception as e:
            await ctx.respond(f"❌ Error al enviar invitación: {format_api_error(e)}")

@plugin.include
@crescent.event
async def on_squad_invite_button(event: hikari.InteractionCreateEvent) -> None:
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return

    custom_id = event.interaction.custom_id
    if not custom_id.startswith("sq_accept_") and not custom_id.startswith("sq_reject_"):
        return

    squad_id = custom_id.split("_", 2)[2]
    discord_id = str(event.interaction.user.id)

    if custom_id.startswith("sq_reject_"):
        embed = hikari.Embed(title="❌ Invitación rechazada", color=UIColors.RED)
        await event.interaction.create_initial_response(hikari.ResponseType.MESSAGE_UPDATE, embed=embed, components=[])
        return

    # Accept Flow
    await event.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    try:
        player = await plugin.model.api.get_player_by_discord(discord_id)
        steam_id = player.steam_id if player else None
        if not steam_id:
            await event.interaction.edit_initial_response(content="❌ Tu cuenta ya no está vinculada a Steam.", components=[])
            return

        await plugin.model.api.add_squad_member(squad_id, steam_id)
        embed = hikari.Embed(title="✅ ¡Has entrado al pelotón!", color=UIColors.GREEN)
        await event.interaction.edit_initial_response(embed=embed, components=[])
    except Exception as e:
        embed = hikari.Embed(title="❌ Error al unirte", description=format_api_error(e), color=UIColors.RED)
        await event.interaction.edit_initial_response(embed=embed, components=[])

@plugin.include
@squad_group.child
@crescent.command(name="kick_member", description="Expulsa a un miembro de tu pelotón (Solo Líder)")
class SquadKickMember:
    usuario = crescent.option(hikari.User, "Usuario a expulsar")
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None, autocomplete=squad_autocomplete)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        if not ctx.member:
            await ctx.respond("❌ Este comando solo se puede usar en el servidor.")
            return
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, str(self.unidad) if self.unidad else None)
            if str(squad.leader_steam_id) != str(steam_id):
                await ctx.respond("❌ Solo el líder del pelotón puede expulsar jugadores.")
                return

            target_player = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            target_steam_id = target_player.steam_id if target_player else None
            if not target_steam_id:
                await ctx.respond(f"❌ {self.usuario.mention} no tiene cuenta vinculada.")
                return

            if target_steam_id == steam_id:
                await ctx.respond("❌ No te puedes expulsar a ti mismo. Usa `/squad disband`.")
                return

            await plugin.model.api.remove_squad_member(squad.id, target_steam_id)
            await ctx.respond(f"✅ {self.usuario.mention} ha sido expulsado del pelotón.")
        except Exception as e:
            await ctx.respond(f"❌ Error al expulsar: {format_api_error(e)}")

# ==========================================
# ADMIN COMMANDS
# ==========================================

@plugin.include
@squad_admin_group.child
@crescent.command(name="squad_delete", description="Elimina a la fuerza un pelotón problemático")
class AdminSquadDelete:
    squad_id = crescent.option(str, "ID del pelotón")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            await plugin.model.api.disband_squad(self.squad_id)
            await ctx.respond(f"✅ Pelotón `{self.squad_id}` disuelto por administrador.")
        except Exception as e:
            await ctx.respond(f"❌ Error: {format_api_error(e)}")

@plugin.include
@squad_admin_group.child
@crescent.command(name="squad_remove_member", description="Expulsa a un jugador de cualquier pelotón a la fuerza")
class AdminSquadRemoveMember:
    squad_id = crescent.option(str, "ID del pelotón")
    usuario = crescent.option(hikari.User, "Jugador a sacar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            target_player = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            target_steam_id = target_player.steam_id if target_player else None
            if not target_steam_id:
                await ctx.respond(f"❌ {self.usuario.mention} no tiene cuenta vinculada.")
                return

            await plugin.model.api.remove_squad_member(self.squad_id, target_steam_id)
            await ctx.respond(f"✅ {self.usuario.mention} ha sido expulsado del pelotón `{self.squad_id}`.")
        except Exception as e:
            await ctx.respond(f"❌ Error: {format_api_error(e)}")

@plugin.include
@squad_group.child
@crescent.command(name="top_members", description="Muestra el top de jugadores dentro de tu pelotón (o de otro)")
class SquadInternalLeaderboard:
    unidad = crescent.option(str, "Tag del pelotón (opcional)", default=None, autocomplete=squad_autocomplete)
    sort_by = crescent.option(str, "Ordenar por", choices=[("Kills", "kills"), ("Muertes", "deaths"), ("Dinero", "cash")], default="kills")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            if self.unidad:
                squad = await plugin.model.api.get_squad_by_tag(str(self.unidad))
            else:
                if not ctx.member:
                    await ctx.respond("❌ Este comando solo se puede usar en el servidor.")
                    return
                steam_id = await get_steam_id_from_member(ctx.member, ctx)
                if not steam_id:
                    return
                squad = await resolve_target_squad(ctx, steam_id)
                
            lb = await plugin.model.api.get_squad_internal_leaderboard(str(squad.id), str(self.sort_by))
            
            if not lb:
                await ctx.respond("No hay estadísticas para este pelotón.")
                return
                
            desc = ""
            for i, p in enumerate(lb[:15]): # Top 15 max
                if self.sort_by == "kills":
                    val = f"{p.kills} ⚔️"
                elif self.sort_by == "deaths":
                    val = f"{p.deaths} 💀"
                else:
                    val = f"${p.cash:,} 💸"
                    
                medal = get_medal(i)
                desc += f"{medal} **{p.in_game_name or 'Unknown'}** - {val}\n"
                
            sort_names = {"kills": "Kills", "deaths": "Muertes", "cash": "Dinero"}
            
            embed = hikari.Embed(
                title=f"🏆 Top [{squad.tag}] {squad.name} - Por {sort_names[str(self.sort_by)]}", 
                description=desc, 
                color=UIColors.GOLD
            )
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al obtener leaderboard: {format_api_error(e)}")

