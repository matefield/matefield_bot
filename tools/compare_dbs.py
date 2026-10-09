import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def compare_dbs():
    url_working = "postgresql+asyncpg://matefield_user:matefield_password@127.0.0.1:5432/matefield_db"
    url_fresh = "postgresql+asyncpg://matefield_user:matefield_password@127.0.0.1:5433/matefield_db"
    
    eng1 = create_async_engine(url_working)
    eng2 = create_async_engine(url_fresh)
    
    tables = [
        "players", "memberships", "player_roles", "roles", "membership_types",
        "matches", "match_player_stats", "match_team_stats",
        "player_sessions", "rcon_servers", "teams", "bot_config"
    ]
    
    print(f"{'TABLE':<22} | {'LOCAL (5432 - Head)':<22} | {'FRESH PROD (5433)':<22} | {'DIFF'}")
    print("-" * 75)
    
    async with eng1.connect() as c1, eng2.connect() as c2:
        for t in tables:
            try:
                cnt1 = (await c1.execute(text(f"SELECT count(*) FROM {t};"))).scalar()
            except Exception:
                cnt1 = "N/A"
            try:
                cnt2 = (await c2.execute(text(f"SELECT count(*) FROM {t};"))).scalar()
            except Exception:
                cnt2 = "N/A"
            
            diff = (cnt1 - cnt2) if isinstance(cnt1, int) and isinstance(cnt2, int) else "N/A"
            diff_str = f"+{diff}" if isinstance(diff, int) and diff > 0 else str(diff)
            print(f"{t:<22} | {cnt1!s:<22} | {cnt2!s:<22} | {diff_str}")

        # Check alembic versions
        v1 = (await c1.execute(text("SELECT version_num FROM alembic_version;"))).scalar()
        v2 = (await c2.execute(text("SELECT version_num FROM alembic_version;"))).scalar()
        print("-" * 75)
        print(f"{'alembic_version':<22} | {v1!s:<22} | {v2!s:<22} | -")

        # Check latest player
        p1 = (await c1.execute(text("SELECT steam_id FROM players ORDER BY steam_id DESC LIMIT 1;"))).scalar()
        p2 = (await c2.execute(text("SELECT steam_id FROM players ORDER BY steam_id DESC LIMIT 1;"))).scalar()
        print(f"{'latest_player_steam':<22} | {p1!s:<22} | {p2!s:<22} | {'IDENTICAL' if p1==p2 else 'DIFFERENT'}")

        # Check active memberships count
        am1 = (await c1.execute(text("SELECT count(*) FROM memberships WHERE is_active = true;"))).scalar()
        am2 = (await c2.execute(text("SELECT count(*) FROM memberships WHERE is_active = true;"))).scalar()
        print(f"{'active_memberships':<22} | {am1!s:<22} | {am2!s:<22} | {am1 - am2}")

    await eng1.dispose()
    await eng2.dispose()

if __name__ == "__main__":
    asyncio.run(compare_dbs())
