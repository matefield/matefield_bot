import sys
with open("apps/discord_bot/src/plugins/squads.py", "r", encoding="utf-8") as f:
    content = f.read()

# Helper to resolve squad
helper = """async def resolve_target_squad(ctx: crescent.Context, steam_id: str, unidad_tag: str | None = None) -> dict:
    squads = await plugin.model.api.get_player_squads(steam_id)
    if not squads:
        raise Exception("No perteneces a ningún pelotón.")
    if unidad_tag:
        for sq in squads:
            if sq['tag'].upper() == unidad_tag.upper():
                return sq
        raise Exception(f"No perteneces a un pelotón con el tag '{unidad_tag}'.")
    if len(squads) > 1:
        raise Exception("Perteneces a más de un pelotón. Usa el parámetro 'unidad' para especificar cuál.")
    return squads[0]"""

content = content.replace("async def get_steam_id_from_member", helper + "\n\nasync def get_steam_id_from_member")

# Replace view_info
old_view_info = """class SquadInfo:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await plugin.model.api.get_player_squad(steam_id)"""
new_view_info = """class SquadInfo:
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, self.unidad)"""
content = content.replace(old_view_info, new_view_info)

# Replace leave_squad
old_leave = """class SquadLeave:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await plugin.model.api.get_player_squad(steam_id)"""
new_leave = """class SquadLeave:
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, self.unidad)"""
content = content.replace(old_leave, new_leave)

# Replace disband
old_disband = """class SquadDisband:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await plugin.model.api.get_player_squad(steam_id)"""
new_disband = """class SquadDisband:
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, self.unidad)"""
content = content.replace(old_disband, new_disband)

# Replace invite_member
old_invite = """class SquadInviteMember:
    usuario = crescent.option(hikari.User, "Usuario a invitar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await plugin.model.api.get_player_squad(steam_id)"""
new_invite = """class SquadInviteMember:
    usuario = crescent.option(hikari.User, "Usuario a invitar")
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, self.unidad)"""
content = content.replace(old_invite, new_invite)

# Replace kick_member
old_kick = """class SquadKickMember:
    usuario = crescent.option(hikari.User, "Usuario a expulsar")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await plugin.model.api.get_player_squad(steam_id)"""
new_kick = """class SquadKickMember:
    usuario = crescent.option(hikari.User, "Usuario a expulsar")
    unidad = crescent.option(str, "Tag del pelotón (si estás en varios)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        steam_id = await get_steam_id_from_member(ctx.member, ctx)
        if not steam_id:
            return

        try:
            squad = await resolve_target_squad(ctx, steam_id, self.unidad)"""
content = content.replace(old_kick, new_kick)

# Add members command
members_cmd = """@plugin.include
@squad_group.child
@crescent.command(name="members", description="Lista los miembros de tu pelotón o de otro especificando el tag")
class SquadMembers:
    unidad = crescent.option(str, "Tag del pelotón (opcional)", default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.defer()
        try:
            if self.unidad:
                squad = await plugin.model.api.get_squad_by_tag(self.unidad)
            else:
                steam_id = await get_steam_id_from_member(ctx.member, ctx)
                if not steam_id:
                    return
                squad = await resolve_target_squad(ctx, steam_id)
                
            members = await plugin.model.api.get_squad_members(squad["id"])
            desc = f"**Líder:** {squad['leader_steam_id']}\n\n"
            for i, mem in enumerate(members):
                desc += f"{i+1}. **{mem.get('in_game_name', 'Unknown')}** (Steam: {mem.get('steam_id')})\n"
                
            embed = hikari.Embed(title=f"👥 Miembros de [{squad['tag']}] {squad['name']}", description=desc, color=UIColors.BLUE)
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al obtener miembros: {format_api_error(e)}")

"""
content = content.replace("@plugin.include\n@squad_group.child\n@crescent.command(name=\"view_info\"", members_cmd + "@plugin.include\n@squad_group.child\n@crescent.command(name=\"view_info\"")

with open("apps/discord_bot/src/plugins/squads.py", "w", encoding="utf-8") as f:
    f.write(content)
