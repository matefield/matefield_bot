import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://matefield_user:matefield_password@localhost:5432/matefield_db"
engine = create_async_engine(DATABASE_URL, echo=False)

async def check_schema_differences():
    print("--- PROFUNDIZANDO EN DISCREPANCIAS DE DB ---")
    async with engine.connect() as conn:
        # Check tables and columns
        tables_query = """
        SELECT table_name, column_name, data_type, character_maximum_length, column_default, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position;
        """
        result = await conn.execute(text(tables_query))
        columns = result.fetchall()
        
        table_dict = {}
        for row in columns:
            t_name = row[0]
            if t_name not in table_dict:
                table_dict[t_name] = []
            table_dict[t_name].append({
                "col": row[1],
                "type": row[2],
                "max_len": row[3],
                "default": row[4],
                "nullable": row[5]
            })
            
        print(f"Total de tablas: {len(table_dict)}")
        
        # Check specific constraints / issues we might have missed
        # 1. Null discord_ids in players?
        print("\n1. Verificando 'discord_id' nulos o vacíos en 'players':")
        res = await conn.execute(text("SELECT COUNT(*) FROM players WHERE discord_id IS NULL OR discord_id = ''"))
        print(f"Jugadores sin discord_id: {res.scalar()}")
        
        # 2. Duplicate codes? (Since we added unique=True to MembershipType.code)
        print("\n2. Verificando duplicados en 'membership_types.code':")
        res = await conn.execute(text("SELECT code, COUNT(*) FROM membership_types GROUP BY code HAVING COUNT(*) > 1"))
        dupes = res.fetchall()
        if dupes:
            print("DUPLICADOS ENCONTRADOS:", dupes)
        else:
            print("OK (No hay duplicados)")

        # 3. Roles orphans? (Players holding roles that don't exist in Discord)
        print("\n3. Verificando roles in-game con 'discord_role_id' nulo:")
        res = await conn.execute(text("SELECT code, name FROM roles WHERE discord_role_id IS NULL"))
        missing_discord_roles = res.fetchall()
        print(f"Roles sin vinculación a Discord: {len(missing_discord_roles)}")
        for r in missing_discord_roles:
            print(f"  - {r[0]}: {r[1]}")
            
        # 4. Check if RconServers has is_default
        print("\n4. Verificando columnas de 'rcon_servers':")
        if "rcon_servers" in table_dict:
            rcon_cols = [c["col"] for c in table_dict["rcon_servers"]]
            print(f"Columnas actuales: {rcon_cols}")
            if "is_default" not in rcon_cols:
                print("FALTA: is_default en rcon_servers")
        else:
            print("FALTA: tabla rcon_servers")
            
        # 5. Check missing foreign keys or bad data types (e.g. price_usd float vs int)
        print("\n5. Verificando tipo de dato de price_usd:")
        if "membership_types" in table_dict:
            price_col = next((c for c in table_dict["membership_types"] if c["col"] == "price_usd"), None)
            if price_col:
                print(f"Tipo actual de price_usd: {price_col['type']}")

        # 6. Check bot_config types
        print("\n6. Verificando tabla bot_config:")
        if "bot_config" in table_dict:
            cfg = table_dict["bot_config"]
            print(f"Columnas: {[c['col'] for c in cfg]}")
            
        # 7. Check if player_sessions has rewarded_seeding_seconds
        print("\n7. Verificando 'player_sessions':")
        if "player_sessions" in table_dict:
            ps_cols = [c["col"] for c in table_dict["player_sessions"]]
            print(f"Columnas: {ps_cols}")
            if "rewarded_seeding_seconds" not in ps_cols:
                print("FALTA: rewarded_seeding_seconds en player_sessions")
                
        # 8. Unused or invalid active memberships
        print("\n8. Verificando membresias huerfanas (steam_id no existe en players):")
        res = await conn.execute(text("SELECT COUNT(*) FROM memberships WHERE steam_id NOT IN (SELECT steam_id FROM players)"))
        print(f"Membresías huerfanas: {res.scalar()}")

if __name__ == "__main__":
    asyncio.run(check_schema_differences())
