import logging

import crescent
import hikari

logger = logging.getLogger("wardogs.hooks")


def _is_system_role(r: dict) -> bool:
    role_type = str(r.get("role_type") or "").strip().upper()
    return (role_type == "SYSTEM" or role_type.startswith("SYSTEM")) and bool(r.get("discord_role_id")) and str(r["discord_role_id"]).isdigit()


def _is_vip_role(r: dict) -> bool:
    role_type = str(r.get("role_type") or "").strip().upper()
    return (role_type == "VIP" or role_type.startswith("VIP")) and bool(r.get("discord_role_id")) and str(r["discord_role_id"]).isdigit()


def _is_guild_owner(ctx: crescent.Context) -> bool:
    try:
        app = getattr(ctx, "app", None) or getattr(getattr(ctx, "client", None), "app", None)
        if app and ctx.guild_id and hasattr(app, "cache"):
            guild = app.cache.get_guild(ctx.guild_id)
            if guild and guild.owner_id == ctx.user.id:
                return True
    except Exception:
        pass
    return False


async def admin_only(ctx: crescent.Context) -> crescent.HookResult:
    if not ctx.member:
        await ctx.respond("Este comando solo puede usarse en un servidor.", flags=hikari.MessageFlag.EPHEMERAL)
        return crescent.HookResult(exit=True)

    # El creador del servidor o alguien con el permiso nativo de Administrador de Discord tiene acceso total
    if _is_guild_owner(ctx):
        return crescent.HookResult()

    if isinstance(ctx.member, hikari.InteractionMember) and (ctx.member.permissions & hikari.Permissions.ADMINISTRATOR) == hikari.Permissions.ADMINISTRATOR:
        return crescent.HookResult()

    try:
        api = getattr(getattr(ctx.client, "model", None), "api", None)
        if not api:
            await ctx.respond("❌ Servicio no disponible.", flags=hikari.MessageFlag.EPHEMERAL)
            return crescent.HookResult(exit=True)
        roles = await api.get_all_roles()
    except Exception as e:
        logger.warning(f"Error verificando roles de admin: {e}")
        await ctx.respond("❌ Error temporal al verificar permisos.", flags=hikari.MessageFlag.EPHEMERAL)
        return crescent.HookResult(exit=True)

    admin_role_ids = [int(r["discord_role_id"]) for r in roles if _is_system_role(r)]

    if any(r in ctx.member.role_ids for r in admin_role_ids):
        return crescent.HookResult()

    await ctx.respond("No tienes permisos de Administrador para usar este comando.", flags=hikari.MessageFlag.EPHEMERAL)
    return crescent.HookResult(exit=True)


async def vip_or_admin(ctx: crescent.Context) -> crescent.HookResult:
    if not ctx.member:
        await ctx.respond("Este comando solo puede usarse en un servidor.", flags=hikari.MessageFlag.EPHEMERAL)
        return crescent.HookResult(exit=True)

    # El creador del servidor o Administradores nativos tienen acceso a comandos VIP
    if _is_guild_owner(ctx):
        return crescent.HookResult()

    if isinstance(ctx.member, hikari.InteractionMember) and (ctx.member.permissions & hikari.Permissions.ADMINISTRATOR) == hikari.Permissions.ADMINISTRATOR:
        return crescent.HookResult()

    try:
        api = getattr(getattr(ctx.client, "model", None), "api", None)
        if not api:
            await ctx.respond("❌ Servicio no disponible.", flags=hikari.MessageFlag.EPHEMERAL)
            return crescent.HookResult(exit=True)
        roles = await api.get_all_roles()
    except Exception as e:
        logger.warning(f"Error verificando roles VIP/admin: {e}")
        await ctx.respond("❌ Error temporal al verificar permisos.", flags=hikari.MessageFlag.EPHEMERAL)
        return crescent.HookResult(exit=True)

    admin_role_ids = [int(r["discord_role_id"]) for r in roles if _is_system_role(r)]
    vip_role_ids = [int(r["discord_role_id"]) for r in roles if _is_vip_role(r)]

    if any(r in ctx.member.role_ids for r in admin_role_ids) or any(r in ctx.member.role_ids for r in vip_role_ids):
        return crescent.HookResult()

    await ctx.respond("No tienes permisos VIP/Admin para usar este comando.", flags=hikari.MessageFlag.EPHEMERAL)
    return crescent.HookResult(exit=True)


async def check_is_admin(ctx: crescent.Context) -> bool:
    if not ctx.member:
        return False

    if _is_guild_owner(ctx):
        return True

    if isinstance(ctx.member, hikari.InteractionMember) and (ctx.member.permissions & hikari.Permissions.ADMINISTRATOR) == hikari.Permissions.ADMINISTRATOR:
        return True

    try:
        client = getattr(ctx, "client", None)
        api = getattr(getattr(client, "model", None), "api", None) if client else None
        if not api:
            return False
        roles = await api.get_all_roles()
        admin_role_ids = [int(r["discord_role_id"]) for r in roles if _is_system_role(r)]
        return any(r in ctx.member.role_ids for r in admin_role_ids)
    except Exception:
        return False
