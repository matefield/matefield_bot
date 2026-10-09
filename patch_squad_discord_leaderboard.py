with open("apps/discord_bot/src/plugins/squads.py", "r", encoding="utf-8") as f:
    content = f.read()

new_command = """@plugin.include
@squad_group.child
@crescent.command(name="leaderboard", description="Muestra el top de jugadores dentro de tu pelotón (o de otro)")
class SquadLeaderboard:
    unidad = crescent.option(str, "Tag del pelotón (opcional)", default=None, autocomplete=squad_autocomplete)
    sort_by = crescent.option(str, "Ordenar por", choices=[("Kills", "kills"), ("Muertes", "deaths"), ("Dinero", "cash")], default="kills")

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
                
            lb = await plugin.model.api.get_squad_internal_leaderboard(squad["id"], self.sort_by)
            
            if not lb:
                await ctx.respond("No hay estadísticas para este pelotón.")
                return
                
            desc = ""
            for i, p in enumerate(lb[:15]): # Top 15 max
                if self.sort_by == "kills":
                    val = f"{p['kills']} ⚔️"
                elif self.sort_by == "deaths":
                    val = f"{p['deaths']} 💀"
                else:
                    val = f"${p['cash']:,} 💸"
                    
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"**{i+1}.**"
                desc += f"{medal} **{p['in_game_name'] or 'Unknown'}** - {val}\n"
                
            sort_names = {"kills": "Kills", "deaths": "Muertes", "cash": "Dinero"}
            
            embed = hikari.Embed(
                title=f"🏆 Top [{squad['tag']}] {squad['name']} - Por {sort_names[self.sort_by]}", 
                description=desc, 
                color=UIColors.GOLD
            )
            await ctx.respond(embed=embed)
        except Exception as e:
            await ctx.respond(f"❌ Error al obtener leaderboard: {format_api_error(e)}")

"""

content += "\n" + new_command

with open("apps/discord_bot/src/plugins/squads.py", "w", encoding="utf-8") as f:
    f.write(content)
