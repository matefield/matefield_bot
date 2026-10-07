import crescent
import hikari
import logging
import re
from typing import Optional
from src.model import Model
from src.hooks import check_is_admin, admin_only

logger = logging.getLogger(__name__)

from src.groups import player_group
from wardogs_schemas.steam_token import create_steam_link_token
from wardogs_config import BOT_SETTINGS
from src.trace import get_tracer
from src.plugins.tasks import sync_single_user_roles

plugin = crescent.Plugin[hikari.GatewayBot, Model]()


def _parse_steam_emoji(raw: Optional[str]) -> hikari.UnicodeEmoji | hikari.CustomEmoji:
    val = (raw or "").strip().strip("\"'")
    if not val:
        return hikari.UnicodeEmoji("🎮")
    if val.isdigit():
        return hikari.CustomEmoji(id=hikari.Snowflake(val), name="steam", is_animated=False)
    if (val.startswith(":") or val.startswith("a:")) and not (val.startswith("<") and val.endswith(">")):
        try:
            return hikari.CustomEmoji.parse(f"<{val}>")
        except Exception:
            pass
    try:
        return hikari.Emoji.parse(val)
    except Exception as exc:
        logger.warning("Invalid STEAM_LINK_EMOJI '%s', falling back to 🎮: %s", raw, exc)
        return hikari.UnicodeEmoji("🎮")


# UI / Theme Constants
STEAM_LINK_EMOJI = _parse_steam_emoji(BOT_SETTINGS.STEAM_LINK_EMOJI)
COLOR_STEAM_DARK = 0x1B2838
COLOR_PANEL_BLUE = 0x2B6CB0
COLOR_PROFILE_DARK = 0x2B2D31
MAX_WELCOME_MESSAGE_LENGTH = 60


def _resolve_guild_id(guild_id: Optional[hikari.Snowflake] = None) -> Optional[hikari.Snowflake]:
    """Resuelve el ID de la guild proporcionada o retorna la primera encontrada en caché."""
    if guild_id:
        return guild_id
    try:
        guilds = list(plugin.app.cache.get_guilds_view())
        if guilds:
            return guilds[0]
    except Exception:
        pass
    return None


def _build_user_steam_link(user: hikari.User, guild_id: Optional[hikari.Snowflake] = None) -> str:
    """Genera una URL firmada de OpenID para vincular Steam con Discord de forma segura."""
    secret_key = plugin.model.api.api_key
    resolved_guild = _resolve_guild_id(guild_id)
    token = create_steam_link_token(
        discord_id=str(user.id),
        secret_key=secret_key,
        guild_id=str(resolved_guild) if resolved_guild else None
    )
    public_url = plugin.model.public_api_url.rstrip("/")
    return f"{public_url}/api/v1/auth/steam/login?token={token}"


STEAM_LINK_CUSTOM_ID = "btn_start_steam_link"


def _display_name(value: str) -> str:
    # Escape Discord formatting and suppress mention syntax in user-controlled names.
    value = str(value).replace("@", "@\u200b").replace("<", "‹").replace(">", "›")
    return re.sub(r"([\\`*_{}\[\]()~|])", r"\\\1", value)


def build_link_panel(rest):
    embed = hikari.Embed(
        title="🔗 Vinculá tu cuenta de Steam | MATEFIELD",
        description=(
            "¡Bienvenido a MATEFIELD!\n\n"
            "Para acceder a las funciones que requieren verificación, **vinculá tus cuentas de Discord y Steam**.\n\n"
            "Al vincularlas vas a poder:\n\n"
            "- ✅ Recibir el rol de miembro verificado, si corresponde.\n"
            "- 📊 Consultar tus estadísticas.\n"
            "- 💎 Usar tus beneficios VIP, si tenés una membresía activa.\n"
            "- 🎁 Reclamar tus recompensas.\n\n"
            "**Para vincular tus cuentas:**\n"
            "1. Tocá **«Vincular mi cuenta de Steam»**.\n"
            "2. En la respuesta privada, tocá **«Ir a Steam»** e iniciá sesión con la cuenta que querés vincular."
        ),
        color=COLOR_PANEL_BLUE,
    )
    row = rest.build_message_action_row()
    row.add_interactive_button(hikari.ButtonStyle.SUCCESS, STEAM_LINK_CUSTOM_ID,
                              label="Vincular mi cuenta de Steam", emoji=STEAM_LINK_EMOJI)
    return embed, row


async def _link_reply(user, guild_id, rest):
    player = await plugin.model.api.get_player_by_discord(str(user.id))
    if player and player.steam_id:
        name = _display_name(user.global_name or user.username)
        steam_name = player.in_game_name
        steam = _display_name(steam_name) if steam_name else "tu cuenta de Steam"
        embed = hikari.Embed(title="Tu cuenta ya está vinculada",
                             description="No tenés que hacer nada más.", color=0x54ED72)
        embed.add_field("Discord", name, inline=True)
        embed.add_field("Steam", steam, inline=True)
        return embed, []
    row = rest.build_message_action_row()
    row.add_link_button(_build_user_steam_link(user, guild_id), label="Ir a Steam", emoji=STEAM_LINK_EMOJI)
    return hikari.Embed(title="Vinculá tu cuenta de Steam",
                        description=("Vas a vincular esta cuenta de Discord con la cuenta de Steam "
                                     "con la que inicies sesión.\n\n"
                                     "Tocá **«Ir a Steam»** para continuar. El enlace vence en **10 minutos**."),
                        color=COLOR_STEAM_DARK), [row]


def _link_error():
    return hikari.Embed(title="No pudimos generar tu enlace",
                        description="Probá de nuevo en unos minutos. Si sigue pasando, contactá al equipo del servidor.",
                        color=COLOR_STEAM_DARK)


@plugin.include
@player_group.child
@crescent.command(name="link", description="Vincula tu cuenta de Discord con Steam de forma segura")
class LinkAccount:
    steam_id = crescent.option(str, "Steam ID (Solo administración / soporte)", default=None)
    usuario = crescent.option(hikari.User, "Usuario a vincular (Solo administración)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)

        # 1. Flujo automático sin parámetros: Genera enlace seguro de Steam OpenID
        if not self.steam_id and not self.usuario:
            try:
                embed, rows = await _link_reply(ctx.user, ctx.guild_id, ctx.app.rest)
                await ctx.respond(embed=embed, components=rows, ephemeral=True,
                                  user_mentions=False, role_mentions=False, mentions_everyone=False)
            except Exception:
                logger.warning("Steam link lookup failed")
                await ctx.respond(embed=_link_error(), ephemeral=True)
            return

        # 2. Flujo manual con parámetros: Exclusivo para administradores
        is_admin = await check_is_admin(ctx)
        if not is_admin:
            await ctx.respond(
                "❌ La vinculación manual con Steam ID está reservada para administradores.\n"
                "Para vincular tu propia cuenta de Steam de forma segura, ejecuta `/player link` sin parámetros.",
                ephemeral=True
            )
            return

        if not self.steam_id:
            await ctx.respond("❌ Debes especificar un Steam ID válido para vincular manualmente.", ephemeral=True)
            return

        target_id = str(self.usuario.id) if self.usuario else str(ctx.user.id)
            
        try:
            await plugin.model.api.link_account(target_id, str(self.steam_id))
            await sync_single_user_roles(ctx.app, plugin.model, int(target_id), ctx.guild_id)
            
            if self.usuario:
                await ctx.respond(f"✅ Has vinculado a {self.usuario.mention} con el Steam ID `{self.steam_id}`.")
            else:
                await ctx.respond(f"✅ Tu cuenta ha sido vinculada exitosamente con el Steam ID `{self.steam_id}`.")
        except Exception as e:
            await ctx.respond(f"❌ Error al vincular: {e}")


@plugin.include
@player_group.child
@crescent.command(name="link_channel", description="Publica un panel permanente con botón para vincular cuentas de Steam")
class LinkChannel:
    canal = crescent.option(hikari.InteractionChannel, "Canal donde publicar el mensaje (Por defecto el canal actual)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        is_admin = await check_is_admin(ctx)
        if not is_admin:
            await ctx.respond("❌ Solo los administradores pueden publicar el panel de vinculación.", ephemeral=True)
            return

        target_channel_id = self.canal.id if self.canal else ctx.channel_id
        
        embed, row = build_link_panel(ctx.app.rest)

        try:
            # Editar el panel del mismo canal para conservar el mensaje fijado.
            old_chan = await plugin.model.api.get_bot_config("LINK_PANEL_CHANNEL_ID")
            old_msg = await plugin.model.api.get_bot_config("LINK_PANEL_MESSAGE_ID")
            new_msg = None
            if old_chan and old_msg and old_chan.isdigit() and old_msg.isdigit():
                try:
                    if int(old_chan) == int(target_channel_id):
                        new_msg = await ctx.app.rest.edit_message(
                            int(old_chan), int(old_msg), embed=embed, components=[row]
                        )
                    else:
                        await ctx.app.rest.delete_message(int(old_chan), int(old_msg))
                except Exception:
                    pass

            if new_msg is None:
                new_msg = await ctx.app.rest.create_message(target_channel_id, embed=embed, components=[row])
            await plugin.model.api.set_bot_config("LINK_PANEL_CHANNEL_ID", str(target_channel_id))
            await plugin.model.api.set_bot_config("LINK_PANEL_MESSAGE_ID", str(new_msg.id))

            await ctx.respond(f"✅ Panel de vinculación publicado exitosamente en <#{target_channel_id}>.", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"❌ Error al publicar en el canal: {e}", ephemeral=True)


@plugin.include
@crescent.event
async def on_steam_link_button_click(event: hikari.InteractionCreateEvent) -> None:
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return
    interaction = event.interaction
    if interaction.custom_id != STEAM_LINK_CUSTOM_ID:
        return
    # Gateway event carries Discord's authenticated user; no identity comes from the browser.
    await interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_CREATE, flags=hikari.MessageFlag.EPHEMERAL
    )
    try:
        embed, rows = await _link_reply(interaction.user, interaction.guild_id, plugin.app.rest)
        await interaction.edit_initial_response(embed=embed, components=rows,
                                                user_mentions=False, role_mentions=False, mentions_everyone=False)
    except Exception as error:
        logger.warning("Steam link interaction failed: %s (status=%s)", type(error).__name__, getattr(error, "status_code", None))
        await interaction.edit_initial_response(embed=_link_error(), components=[])



@plugin.include
@crescent.hook(admin_only)
@player_group.child
@crescent.command(name="unlink", description="Desvincula una cuenta de Discord de Steam (Solo Administrador)")
class UnlinkAccount:
    usuario = crescent.option(hikari.User, "Usuario de Discord a desvincular", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        tracer = get_tracer()
        discord_id = str(self.usuario.id) if self.usuario else str(ctx.user.id)

        try:
            with tracer.measure("Desvincular cuenta en API", category="DB", action="DELETE", target=f"Discord {discord_id}") as t:
                await plugin.model.api.unlink_account(discord_id)
                t["details"] = "Vínculo Steam eliminado en BD"

            with tracer.measure("Sincronizar roles Discord", category="DISCORD", action="SYNC", target=f"Discord {discord_id}") as t:
                sync_res = await sync_single_user_roles(ctx.app, plugin.model, int(discord_id), ctx.guild_id)
                t["details"] = f"Roles removidos: {sync_res.get('removed', 0)}"

            if self.usuario:
                base_msg = f"✅ La cuenta de {self.usuario.mention} ha sido desvinculada."
            else:
                base_msg = "✅ Tu cuenta de Discord ha sido desvinculada."

            await ctx.respond(tracer.append_to_message(base_msg))
        except Exception as e:
            await ctx.respond(tracer.append_to_message(f"❌ Error al desvincular: {e}"))

@plugin.include
@crescent.hook(admin_only)
@player_group.child
@crescent.command(name="welcome_message_set", description="Establece un mensaje de bienvenida personalizado (VIP/ADMIN)")
class SetWelcomeMessage:
    message = crescent.option(str, "El mensaje que se mostrará cuando entres al servidor")
    steam_id = crescent.option(str, "Steam ID del jugador a editar (opcional)", default=None)
    usuario = crescent.option(hikari.User, "Usuario de Discord a editar (opcional)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=False)
        
        if len(self.message) > MAX_WELCOME_MESSAGE_LENGTH:
            await ctx.respond(f"❌ El mensaje no puede tener más de {MAX_WELCOME_MESSAGE_LENGTH} caracteres.")
            return
            
        target_steam = self.steam_id
        if self.usuario:
            db_player = await plugin.model.api.get_player_by_discord(str(self.usuario.id))
            if not db_player:
                await ctx.respond(f"❌ El usuario {self.usuario.mention} no tiene una cuenta vinculada.")
                return
            target_steam = db_player.steam_id
            
        if not target_steam:
            discord_id = str(ctx.user.id)
            user_data = await plugin.model.api.get_player_by_discord(discord_id)
            if not user_data or not user_data.steam_id:
                await ctx.respond("❌ Debes vincular tu cuenta de Steam primero usando `/player link` o especificar a quién editar.")
                return
            target_steam = user_data["steam_id"]
            
        steam_data = await plugin.model.api.get_player_by_steam(str(target_steam))
        active_role = steam_data.get("active_role") if steam_data else None
        
        if not active_role:
            await ctx.respond(f"❌ El jugador no tiene una membresía VIP o ADMIN activa. No se puede establecer el mensaje.")
            return
            
        await plugin.model.api.set_welcome_message(str(target_steam), self.message)
        preview_msg = f"El {active_role} [Nombre en Juego] se conectó: \"{self.message}\""
        await ctx.respond(f"✅ **Mensaje de bienvenida establecido.**\n👀 **Vista Previa:**\n> {preview_msg}")

@plugin.include
@player_group.child
@crescent.command(name="profile", description="Muestra el perfil histórico de un jugador o el tuyo")
class Profile:
    usuario = crescent.option(hikari.User, "Usuario de Discord a consultar (opcional)", default=None)
    steam_id = crescent.option(str, "Steam ID a consultar (opcional)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=False)
        
        target_discord_id = str(self.usuario.id) if self.usuario else None
        target_steam_id = self.steam_id
        
        # If no arguments provided, use caller
        if not target_discord_id and not target_steam_id:
            target_discord_id = str(ctx.user.id)
            
        user_data = None
        if target_discord_id:
            user_data = await plugin.model.api.get_player_by_discord(target_discord_id)
            if not user_data or not user_data.steam_id:
                if target_discord_id == str(ctx.user.id):
                    await ctx.respond("❌ No tienes ninguna cuenta de Steam vinculada. Usa /player link primero.")
                else:
                    await ctx.respond("❌ Ese usuario no tiene cuenta de Steam vinculada.")
                return
            target_steam_id = user_data.steam_id
            
        steam_data = await plugin.model.api.get_player_by_steam(str(target_steam_id))
        
        if not steam_data:
            await ctx.respond(f"❌ La cuenta de Steam {target_steam_id} no tiene perfil en nuestra base de datos aún (debe entrar a jugar una vez).")
            return
            
        stats_data = await plugin.model.api.get_player_historical_stats(str(target_steam_id))
            
        # Parse data
        memberships = getattr(steam_data, "active_memberships", None) or getattr(steam_data, "memberships", [])
        special_roles = getattr(steam_data, "roles", [])
        active_role = getattr(steam_data, "role", "Ninguno")
        if not active_role:
            active_role = "Ninguno"
        
        # We need to fetch the Steam API for the real name if it's not in our DB
        in_game_name = getattr(steam_data, "name", None) or getattr(steam_data, "in_game_name", None) or "Desconocido"
        
        linked_discord = getattr(steam_data, "discord_id", None)
        
        # Build embed
        embed = hikari.Embed(
            title=f"Perfil de Jugador: {in_game_name}",
            description=f"**Steam ID:** {target_steam_id}",
            color=COLOR_PROFILE_DARK
        )
        avatar_url = getattr(steam_data, "avatar_url", None)
        if avatar_url:
            embed.set_thumbnail(avatar_url)
            
        if linked_discord:
            embed.add_field(name="🔗 Discord Vinculado", value=f"<@{linked_discord}>", inline=False)
        else:
            embed.add_field(name="🔗 Discord Vinculado", value="No vinculado", inline=False)
            
        # Add roles
        mem_str = "\n".join([f"• {m['type']} (Vence: {m.get('end_time') or 'Permanente'})" for m in memberships])
        if not mem_str: mem_str = "Ninguna"
        embed.add_field(name="👑 Membresías Activas", value=mem_str, inline=True)
        
        roles_str = "\n".join([f"• {r}" for r in special_roles])
        if not roles_str: roles_str = "Ninguno"
        embed.add_field(name="🏷️ Roles Especiales", value=roles_str, inline=True)
        
        
        # Rango RCON y Observaciones Internas solo son visibles si un administrador usa el comando
        is_admin = await check_is_admin(ctx)
        if is_admin:
            embed.add_field(name="⭐ Rango RCON", value=active_role, inline=False)
            obs = getattr(steam_data, "observations", None)
            if obs:
                embed.add_field(name="📝 Observaciones Internas", value=f"```{obs}```", inline=False)

        
        # Stats
        if stats_data:
            kills = stats_data.get("total_kills", 0)
            deaths = stats_data.get("total_deaths", 0)
            cash = stats_data.get("total_cash_earned", stats_data.get("total_cash", 0))
            matches = stats_data.get("matches_played", 0)
            embed.add_field(name="📊 Estadísticas Históricas", value=f"**Partidas jugadas:** {matches}\n**Kills:** {kills} | **Deaths:** {deaths}\n**Cash total:** ${cash}", inline=False)
            
        await ctx.respond(embed=embed)
