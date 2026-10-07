import logging
from typing import Optional
import crescent
import hikari

from src.model import Model
from src.hooks import admin_only, check_is_admin
from src.groups import rewards_group, rewards_admin_group

logger = logging.getLogger(__name__)

plugin = crescent.Plugin[hikari.GatewayBot, Model]()

from src.ui_utils import UIColors


async def autocomplete_active_rewards(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    val = str(option.value or "").strip().lower()
    try:
        catalog = await plugin.model.api.get_rewards_catalog(only_active=True)
        results = []
        for r in catalog:
            code = r.code
            name = r.name or code
            cost = r.cost_points
            dtype = "⚡ Auto" if r.delivery_type == "AUTOMATIC" else "🎟️ Ticket"
            label = f"{name} ({cost} pts) [{dtype}]"[:100]
            if not val or val in code.lower() or val in name.lower():
                results.append((label, code))
        return results[:25]
    except Exception:
        return []


# =========================================================================
# User Commands (/rewards ...)
# =========================================================================

@plugin.include
@rewards_group.child
@crescent.command(name="balance", description="Consulta tus puntos acumulados y tiempo de seeding")
class RewardsBalance:
    usuario = crescent.option(hikari.User, "Usuario a consultar (Solo admins pueden ver a terceros)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        target = self.usuario or ctx.user

        if target.id != ctx.user.id:
            is_admin = await check_is_admin(ctx)
            if not is_admin:
                await ctx.respond("❌ No tienes permisos para ver el balance de otros usuarios.", ephemeral=True)
                return

        try:
            data = await plugin.model.api.get_player_rewards_balance(str(target.id))
        except Exception as e:
            err_msg = str(e)
            if "no encontrado" in err_msg.lower() or "404" in err_msg:
                await ctx.respond(
                    f"⚠️ {target.mention} no tiene una cuenta vinculada a Steam. "
                    "Usa `/player link` para vincular tu cuenta y empezar a ganar puntos de seeding.",
                    ephemeral=True,
                )
                return
            await ctx.respond(f"❌ Error al consultar balance: {err_msg}", ephemeral=True)
            return

        points = data.reward_points
        seeding_mins = data.total_seeding_minutes
        next_point_mins = data.next_point_minutes_left
        
        hours = seeding_mins // 60
        mins = seeding_mins % 60
        time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins} minutos"
        in_game = data.in_game_name or "Sin registrar"
        steam_id = data.steam_id or "Desconocido"

        embed = hikari.Embed(
            title="🏆 Centro de Recompensas y Seeding",
            description=f"Perfil de recompensas para {target.mention}",
            color=UIColors.GOLD,
        )
        embed.add_field(name="🎮 Jugador", value=f"**{in_game}**\n`{steam_id}`", inline=True)
        embed.add_field(name="⭐ Puntos Disponibles", value=f"**{points:,}** pts", inline=True)
        embed.add_field(name="⏱️ Tiempo Total de Seeding", value=f"**{time_str}**", inline=True)
        embed.add_field(name="⏳ Siguiente Punto En", value=f"**{next_point_mins} mins**", inline=True)

        claims = getattr(data, "active_claims", getattr(data, "claims", []))
        pending_claims = [c for c in claims if c.status == "PENDING"]
        if pending_claims:
            vouchers_text = []
            for c in pending_claims[:5]:
                vouchers_text.append(f"• **{c.reward_name}**: Código `{c.claim_code}`")
            embed.add_field(
                name="🎫 Canjes Pendientes (Tickets)",
                value="\n".join(vouchers_text) + "\n*Abre un ticket de soporte y presenta tu código.*",
                inline=False,
            )

        embed.set_footer(text="Gana puntos jugando durante las horas de siembra/seeding en el servidor.")
        await ctx.respond(embed=embed, ephemeral=True)


@plugin.include
@rewards_group.child
@crescent.command(name="catalog", description="Explora el catálogo de recompensas disponibles")
class RewardsCatalog:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            items = await plugin.model.api.get_rewards_catalog(only_active=True)
        except Exception as e:
            await ctx.respond(f"❌ Error al cargar catálogo: {e}", ephemeral=True)
            return

        if not items:
            await ctx.respond("ℹ️ No hay recompensas disponibles en este momento.", ephemeral=True)
            return

        embed = hikari.Embed(
            title="🎁 Catálogo de Recompensas",
            description="Acumula puntos de seeding y canjéalos por beneficios exclusivos:",
            color=UIColors.GREEN,
        )

        for item in items:
            code = item.code
            name = item.name
            cost = item.cost_points
            desc = item.description or "Sin descripción"
            dtype = "⚡ Automático" if item.delivery_type == "AUTOMATIC" else "🎟️ Ticket Soporte"
            
            value_line = f"**Costo:** `{cost} pts` | **Entrega:** `{dtype}`\n{desc}\n`Código:` **`{code}`**"
            embed.add_field(name=f"🏅 {name}", value=value_line, inline=False)

        embed.set_footer(text="Canjea cualquier recompensa usando /rewards claim [código]")
        await ctx.respond(embed=embed, ephemeral=True)


@plugin.include
@rewards_group.child
@crescent.command(name="claim", description="Canjea tus puntos por una recompensa del catálogo")
class RewardsClaim:
    recompensa = crescent.option(
        str,
        "Recompensa a canjear",
        autocomplete=autocomplete_active_rewards,
    )

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            result = await plugin.model.api.claim_reward(str(ctx.user.id), str(self.recompensa))
        except Exception as e:
            err_msg = str(e)
            if "no encontrado" in err_msg.lower() or "404" in err_msg:
                await ctx.respond(
                    "⚠️ Tu cuenta de Discord no está vinculada. Usa `/player link` para vincularte primero.",
                    ephemeral=True,
                )
                return
            if "insuficientes" in err_msg.lower():
                await ctx.respond(f"❌ {err_msg}", ephemeral=True)
                return
            await ctx.respond(f"❌ Error al canjear recompensa: {err_msg}", ephemeral=True)
            return

        claim_code = result.claim_code
        reward_name = result.reward_name
        points_spent = result.cost_points
        remaining = result.remaining_points
        delivery = result.delivery
        dtype = delivery.delivery_type

        if dtype == "AUTOMATIC":
            embed = hikari.Embed(
                title="🎉 ¡Canje Exitoso y Entregado!",
                description=(
                    f"Has canjeado **{reward_name}** por **{points_spent} pts**.\n\n"
                    "⚡ Tu beneficio ya ha sido activado automáticamente en el servidor y bot.\n"
                    f"Puntos restantes: **{remaining} pts**"
                ),
                color=UIColors.GREEN,
            )
        else:
            instructions = delivery.instructions or "Abre un ticket de soporte y proporciona tu código."
            embed = hikari.Embed(
                title="🎫 ¡Canje Registrado Exitosamente!",
                description=(
                    f"Has canjeado **{reward_name}** por **{points_spent} pts**.\n\n"
                    f"🔑 **Tu Código de Canje:** `{claim_code}`\n\n"
                    f"{instructions}\n\n"
                    f"Puntos restantes: **{remaining} pts**"
                ),
                color=UIColors.BLUE,
            )

        embed.set_footer(text="Conserva tu código de canje en caso de requerir soporte.")
        await ctx.respond(embed=embed, ephemeral=True)


# =========================================================================
# Admin Commands (/rewards admin ...)
# =========================================================================

@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="set_threshold", description="Configura el número máximo de jugadores para contar seeding (Admin)")
class RewardsSetThreshold:
    limite = crescent.option(int, "Cantidad de personas (ej: 20). Si hay menos, cuenta tiempo de seed")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        if self.limite < 1:
            await ctx.respond("❌ El límite debe ser al menos 1.", ephemeral=True)
            return
        await plugin.model.api.set_bot_config("SEEDING_MIN_PLAYERS", str(self.limite))
        await ctx.respond(f"✅ Umbral de seeding actualizado: Menos de **{self.limite}** jugadores contará como seed.")


@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="set_min_players", description="Configura el mínimo de jugadores para empezar a contar seeding (Admin)")
class RewardsSetMinPlayers:
    minimo = crescent.option(int, "Cantidad mínima (ej: 4). Menos de esto se ignora (evita AFK farming)")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        if self.minimo < 1:
            await ctx.respond("❌ El mínimo debe ser al menos 1.", ephemeral=True)
            return
        await plugin.model.api.set_bot_config("SEEDING_MIN_PLAYERS_TO_COUNT", str(self.minimo))
        await ctx.respond(f"✅ Límite inferior actualizado: Se requieren al menos **{self.minimo}** jugadores para empezar a contar seeding.")

@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="set_rate", description="Configura los minutos necesarios para ganar 1 punto (Admin)")
class RewardsSetRate:
    minutos = crescent.option(int, "Minutos necesarios por cada 1 punto de recompensa (ej: 30)")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        if self.minutos < 1:
            await ctx.respond("❌ Los minutos deben ser al menos 1.", ephemeral=True)
            return
        await plugin.model.api.set_bot_config("SEEDING_MINUTES_PER_POINT", str(self.minutos))
        await ctx.respond(f"✅ Tasa de recompensas actualizada: Se otorgará **1 punto** cada **{self.minutos}** minutos de seeding.")


@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="verify", description="Verifica un código de voucher o canje (Admin)")
class RewardsVerifyClaim:
    codigo_canje = crescent.option(str, "Código de voucher a verificar (ej: MF-XXXX-XXXX)")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            data = await plugin.model.api.verify_reward_claim(str(self.codigo_canje))
        except Exception as e:
            await ctx.respond(f"❌ Error o código inexistente: {e}", ephemeral=True)
            return

        status = data.get("status")
        status_color = UIColors.GREEN if status == "DELIVERED" else (UIColors.GOLD if status == "PENDING" else UIColors.RED)
        embed = hikari.Embed(
            title=f"🔎 Verificación de Voucher: `{data.get('claim_code')}`",
            color=status_color,
        )
        embed.add_field(name="Estado", value=f"**{status}**", inline=True)
        embed.add_field(name="Recompensa", value=f"{data.get('reward_name')} (`{data.get('reward_code')}`)", inline=True)
        embed.add_field(name="Costo", value=f"{data.get('points_spent')} pts", inline=True)
        embed.add_field(name="Steam ID", value=f"`{data.get('steam_id')}`", inline=True)
        embed.add_field(name="Discord", value=f"<@{data.get('discord_id')}>" if data.get("discord_id") else "No vinculado", inline=True)
        embed.add_field(name="Fecha Canje", value=str(data.get("claimed_at")), inline=True)

        if data.get("delivered_at"):
            embed.add_field(name="Entregado Por", value=f"{data.get('delivered_by')} el {data.get('delivered_at')}", inline=False)
        if data.get("notes"):
            embed.add_field(name="Notas / Razón", value=str(data.get("notes")), inline=False)

        await ctx.respond(embed=embed, ephemeral=True)


@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="deliver", description="Marca una recompensa manual de ticket como entregada (Admin)")
class RewardsDeliverClaim:
    codigo_canje = crescent.option(str, "Código de voucher a entregar")
    notas = crescent.option(str, "Notas adicionales (ej: Steam Key o confirmación)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            res = await plugin.model.api.deliver_reward_claim(
                str(self.codigo_canje),
                delivered_by=str(ctx.user),
                notes=str(self.notas) if self.notas else None,
            )
            await ctx.respond(f"✅ {res.get('message', 'Marcado como entregado con éxito.')}")
        except Exception as e:
            await ctx.respond(f"❌ Error al entregar: {e}", ephemeral=True)


@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="refund", description="Reembolsa un canje y devuelve los puntos al jugador (Admin)")
class RewardsRefundClaim:
    codigo_canje = crescent.option(str, "Código de voucher a reembolsar")
    motivo = crescent.option(str, "Motivo del reembolso (ej: Falta de stock de keys)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            res = await plugin.model.api.refund_reward_claim(
                str(self.codigo_canje),
                refunded_by=str(ctx.user),
                reason=str(self.motivo) if self.motivo else None,
            )
            await ctx.respond(f"✅ {res.get('message', 'Reembolso procesado con éxito.')}")
        except Exception as e:
            await ctx.respond(f"❌ Error al reembolsar: {e}", ephemeral=True)


@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="give_points", description="Otorga o descuenta puntos a un jugador manualmente (Admin)")
class RewardsGivePoints:
    puntos = crescent.option(int, "Cantidad de puntos a sumar (positivo) o restar (negativo)")
    usuario = crescent.option(hikari.User, "Usuario de Discord a modificar", default=None)
    steam_id = crescent.option(str, "Steam ID del jugador a modificar", default=None)
    motivo = crescent.option(str, "Motivo del ajuste", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        target = str(self.steam_id) if self.steam_id else (str(self.usuario.id) if self.usuario else None)
        if not target:
            await ctx.respond("❌ Debes especificar un usuario de Discord o un Steam ID.", ephemeral=True)
            return

        try:
            res = await plugin.model.api.give_reward_points(
                target,
                int(self.puntos),
                str(self.motivo) if self.motivo else None,
            )
            sign = "+" if self.puntos >= 0 else ""
            await ctx.respond(
                f"✅ Puntos ajustados para `{res.get('steam_id')}`: **{sign}{self.puntos} pts**.\n"
                f"Nuevo saldo: **{res.get('new_balance')} pts**."
            )
        except Exception as e:
            await ctx.respond(f"❌ Error al ajustar puntos: {e}", ephemeral=True)


@plugin.include
@crescent.hook(admin_only)
@rewards_admin_group.child
@crescent.command(name="add_item", description="Añade o actualiza una recompensa en el catálogo (Admin)")
class RewardsAddItem:
    codigo = crescent.option(str, "Código único (ej: VIP_15D, KEY_GAME)")
    nombre = crescent.option(str, "Nombre visible de la recompensa")
    costo = crescent.option(int, "Costo en puntos")
    tipo_entrega = crescent.option(
        str,
        "Tipo de entrega",
        choices=[("AUTOMATIC (Inmediata por el bot)", "AUTOMATIC"), ("MANUAL_TICKET (Vía ticket con voucher)", "MANUAL_TICKET")],
    )
    tipo_recompensa = crescent.option(
        str,
        "Tipo de recompensa técnica",
        choices=[("MEMBERSHIP (Membresía VIP)", "MEMBERSHIP"), ("ROLE (Rol especial)", "ROLE"), ("CUSTOM (Personalizada)", "CUSTOM")],
    )
    valor = crescent.option(str, "Código de membresía (ej: VIP), rol o detalle técnico")
    duracion_dias = crescent.option(int, "Duración en días (solo para membresías, opcional)", default=None)
    descripcion = crescent.option(str, "Descripción detallada", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer(ephemeral=True)
        try:
            res = await plugin.model.api.create_or_update_reward_item(
                code=str(self.codigo),
                name=str(self.nombre),
                cost_points=int(self.costo),
                delivery_type=str(self.tipo_entrega),
                reward_type=str(self.tipo_recompensa),
                reward_value=str(self.valor),
                duration_days=int(self.duracion_dias) if self.duracion_dias is not None else None,
                description=str(self.descripcion) if self.descripcion else None,
                is_active=True,
            )
            await ctx.respond(f"✅ Recompensa '{res.name}' ({res.code}) configurada exitosamente.")
        except Exception as e:
            await ctx.respond(f"❌ Error al configurar recompensa: {e}", ephemeral=True)


