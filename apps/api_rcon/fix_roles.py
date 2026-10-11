import asyncio

from sqlmodel import text
from src.connections.databases.db import (
    engine,
)


async def main():
    async with engine.begin() as conn:
        print("🔧 Iniciando fix de roles (Cruce de datos post-migración)...")

        # 1. Corregir membership_types (Eliminar los IDs quemados por la migración j6f7a8b9c0d1)
        print("1️⃣ Mapeando membership_types.role_id usando el 'code' en lugar de IDs quemados...")
        await conn.execute(text("""
            UPDATE membership_types mt
            SET role_id = r.id
            FROM roles r
            WHERE upper(mt.code) = upper(r.code);
        """))

        # 2. Corregir memberships (Re-asignar el role_granted_id correcto)
        print("2️⃣ Corrigiendo memberships.role_granted_id basándose en membership_types actualizado...")
        await conn.execute(text("""
            UPDATE memberships m
            SET role_granted_id = mt.role_id
            FROM membership_types mt
            WHERE upper(m.type) = upper(mt.code);
        """))

        # 3. Limpiar player_roles incorrectos (Solo eliminamos los roles de tipo VIP para re-asignarlos)
        print("3️⃣ Limpiando player_roles incorrectos (Tipo VIP)...")
        await conn.execute(text("""
            DELETE FROM player_roles
            WHERE role_id IN (
                SELECT id FROM roles WHERE role_type = 'VIP'
            );
        """))

        # 4. Re-asignar los roles correctos a player_roles
        print("4️⃣ Reasignando los roles VIP correctos a los jugadores con membresía activa...")
        res = await conn.execute(text("""
            INSERT INTO player_roles (steam_id, role_id)
            SELECT DISTINCT m.steam_id, m.role_granted_id
            FROM memberships m
            WHERE m.is_active = true
              AND (m.end_date IS NULL OR m.end_date > NOW())
              AND m.role_granted_id IS NOT NULL
            ON CONFLICT (steam_id, role_id) DO NOTHING
            RETURNING steam_id;
        """))
        
        inserted = res.fetchall()
        print(f"✅ Se re-asignaron roles a {len(inserted)} membresías activas.")

        print("🚀 ¡Fix completado! Los roles cruzados han sido corregidos.")

if __name__ == "__main__":
    asyncio.run(main())
