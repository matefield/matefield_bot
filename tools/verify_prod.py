import asyncio

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def post_migration_prod():
    cfg = dotenv_values(".env.prod")
    db_url = cfg.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not found in .env.prod")
    engine = create_async_engine(db_url)
    
    print("=== ASIGNANDO ROLES ADMIN EN PROD ===")
    admin_steam_ids = ["76561199157256458", "76561198151376508"]
    
    async with engine.begin() as conn:
        for sid in admin_steam_ids:
            await conn.execute(text("""
                INSERT INTO player_roles (steam_id, role_id)
                VALUES (:sid, 1)
                ON CONFLICT (steam_id, role_id) DO NOTHING;
            """), {"sid": sid})
            print(f"Role 1 (ADMIN) asegurado para {sid}")

    print("\n=== VERIFICANDO CONSISTENCIA DE DATOS EN PROD ===")
    async with engine.connect() as conn:
        # 1. Alembic version
        v = (await conn.execute(text("SELECT version_num FROM alembic_version;"))).scalar()
        print(f"1. Alembic version: {v}")
        assert v == "k7g8b9c0d1e2", f"Expected k7g8b9c0d1e2, got {v}"

        # 2. Membership Types
        res_mt = await conn.execute(text("""
            SELECT mt.id, mt.code, mt.name, mt.role_id, mt.base_price_usd, mt.price_usd, r.name as role_name
            FROM membership_types mt
            LEFT JOIN roles r ON mt.role_id = r.id
            ORDER BY mt.id;
        """))
        print("\n2. Membership Types:")
        for row in res_mt.fetchall():
            print(f"   - {row.code} ({row.name}): role_id={row.role_id} [{row.role_name}], base=${row.base_price_usd}, price=${row.price_usd}")

        # 3. Admins verification
        print("\n3. Verificación de Administradores en player_roles:")
        res_adm = await conn.execute(text("""
            SELECT pr.steam_id, pr.role_id, r.code, r.role_type
            FROM player_roles pr
            JOIN roles r ON pr.role_id = r.id
            WHERE pr.steam_id IN ('76561199157256458', '76561198151376508')
            ORDER BY pr.steam_id, pr.role_id;
        """))
        for row in res_adm.fetchall():
            print(f"   - Steam: {row.steam_id} | Role: {row.code} ({row.role_type}) | role_id={row.role_id}")

        # 4. Total rows count
        print("\n4. Conteo de filas post-migración:")
        for t in ["players", "memberships", "player_roles", "roles", "membership_types"]:
            cnt = (await conn.execute(text(f"SELECT count(*) FROM {t};"))).scalar()
            print(f"   - {t:<18}: {cnt}")

        # 5. Active memberships check
        active_cnt = (await conn.execute(text("SELECT count(*) FROM memberships WHERE is_active = true;"))).scalar()
        print(f"   - Active memberships: {active_cnt}")

        # 6. Check that no active membership has NULL role_granted_id
        null_roles = (await conn.execute(text("""
            SELECT count(*) FROM memberships 
            WHERE is_active = true AND role_granted_id IS NULL;
        """))).scalar()
        print(f"   - Active memberships with NULL role_granted_id: {null_roles} (debe ser 0)")
        assert null_roles == 0, f"Found {null_roles} active memberships with NULL role_granted_id!"

    await engine.dispose()
    print("\n[OK] TODAS LAS VALIDACIONES DE PROD PASARON CON EXITO.")

if __name__ == "__main__":
    asyncio.run(post_migration_prod())
