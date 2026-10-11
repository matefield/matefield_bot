import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://matefield_user:matefield_password@localhost:5432/matefield_db"
engine = create_async_engine(DATABASE_URL, echo=False)

async def main():
    print("--- ANALISIS DE IMPACTO DE DB DE PROD ---")
    async with engine.connect() as conn:
        # 1. Jugadores con Steam IDs mal formateados (minúsculas o espacios)
        print("\n1. Buscando Steam IDs con espacios o minúsculas...")
        result = await conn.execute(text("SELECT steam_id FROM players WHERE steam_id != UPPER(TRIM(steam_id))"))
        bad_steam_ids = result.fetchall()
        print(f"Usuarios afectados (Steam ID mal formateado): {len(bad_steam_ids)}")
        for r in bad_steam_ids[:5]:
            print(f"  - '{r[0]}'")
        if len(bad_steam_ids) > 5: print("  ...")

        # 2. Jugadores con puntos de recompensa negativos
        print("\n2. Buscando Jugadores con reward_points negativos (violarían el nuevo CHECK)...")
        result = await conn.execute(text("SELECT steam_id, reward_points FROM players WHERE reward_points < 0"))
        neg_points = result.fetchall()
        print(f"Usuarios afectados (reward_points < 0): {len(neg_points)}")
        for r in neg_points[:5]:
            print(f"  - {r[0]}: {r[1]} pts")
        if len(neg_points) > 5: print("  ...")

        # 3. Claims de recompensas con gastos negativos
        print("\n3. Buscando claims con points_spent negativos (violarían el nuevo CHECK)...")
        result = await conn.execute(text("SELECT id, steam_id, points_spent FROM reward_claims WHERE points_spent < 0"))
        neg_claims = result.fetchall()
        print(f"Reclamos afectados (points_spent < 0): {len(neg_claims)}")
        for r in neg_claims[:5]:
            print(f"  - Reclamo ID {r[0]} (Usuario {r[1]}): gastó {r[2]} pts")
        if len(neg_claims) > 5: print("  ...")

        # 4. Membresías que duran menos que su fecha de inicio (fechas invertidas)
        print("\n4. Buscando membresías con start_date > end_date...")
        result = await conn.execute(text("SELECT id, steam_id, start_date, end_date FROM memberships WHERE end_date IS NOT NULL AND start_date > end_date"))
        bad_dates = result.fetchall()
        print(f"Membresías afectadas (Fechas invertidas): {len(bad_dates)}")
        for r in bad_dates[:5]:
            print(f"  - Membresía ID {r[0]}: Start {r[2]} > End {r[3]}")
        if len(bad_dates) > 5: print("  ...")
        
        # 5. Tipos de membresía con precios decimales en su base original
        print("\n5. Buscando Tipos de Membresía (Conversión Float -> Integer Cents)...")
        result = await conn.execute(text("SELECT id, name, price_usd FROM membership_types"))
        m_types = result.fetchall()
        for r in m_types:
            print(f"  - [{r[0]}] {r[1]}: {r[2]}")

if __name__ == "__main__":
    asyncio.run(main())
