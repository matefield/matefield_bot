from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import Membership, Player, Role
from src.modules.v1.services.backup_service import (
    _escape_sql_value,
    cleanup_old_backups,
    create_database_sql_backup,
)
from src.modules.v1.services.export_service import (
    generate_export_download_token,
    generate_memberships_csv,
    verify_export_download_token,
)


def test_export_download_token():
    token = generate_export_download_token("memberships_export.csv", expires_in_seconds=60)
    assert verify_export_download_token("memberships_export.csv", token) is True
    assert verify_export_download_token("wrong_file.csv", token) is False
    assert verify_export_download_token("memberships_export.csv", "invalid_token") is False

    # Expired token
    expired_token = generate_export_download_token("memberships_export.csv", expires_in_seconds=-5)
    assert verify_export_download_token("memberships_export.csv", expired_token) is False


def test_sql_escape_value():
    assert _escape_sql_value(None) == "NULL"
    assert _escape_sql_value(True) == "TRUE"
    assert _escape_sql_value(False) == "FALSE"
    assert _escape_sql_value(42) == "42"
    assert _escape_sql_value("O'Reilly") == "'O''Reilly'"
    assert _escape_sql_value("Simple string") == "'Simple string'"


@pytest.mark.asyncio
async def test_sql_backup_and_csv_export(tmp_path: Path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        # Seed test players, roles, and memberships
        s1 = "76561198000000001"
        s2 = "76561198000000002"
        p1 = Player(steam_id=s1, discord_id="1234567890", in_game_name="CapitanMate", observations="VIP Fundador")
        p2 = Player(steam_id=s2, discord_id=None, in_game_name="SoldadoRaso")
        r_special = Role(id=1, code="VIP_ESPECIAL", name="Rol Especial", role_type="SPECIAL")
        r_founder = Role(id=2, code="FUNDADOR", name="Fundador", role_type="SPECIAL")

        session.add(p1)
        session.add(p2)
        session.add(r_special)
        session.add(r_founder)
        await session.commit()

        t0 = datetime(2025, 1, 1, tzinfo=UTC)
        t1 = datetime(2025, 3, 1, tzinfo=UTC)
        t2 = datetime(2025, 5, 1, tzinfo=UTC)

        m_old = Membership(steam_id=s1, membership_type="VIP_COMUN", start_time=t0, is_active=False)
        m_founder = Membership(steam_id=s1, membership_type="VIP_COMUN", start_time=t1, is_booster=True, special_role_id=2, is_active=False)
        m_renew = Membership(steam_id=s1, membership_type="VIP_EXPRESS", start_time=t2, is_active=True)
        session.add(m_old)
        session.add(m_founder)
        session.add(m_renew)
        await session.commit()

        # 1. Test SQL backup
        backup_dir = tmp_path / "backups"
        sql_file = await create_database_sql_backup(session, backup_dir=backup_dir)
        assert sql_file.exists()
        assert (backup_dir / "latest.sql").exists()

        content = sql_file.read_text(encoding="utf-8")
        assert "BEGIN;" in content
        assert "COMMIT;" in content
        assert "INSERT INTO" in content
        assert s1 in content

        # 2. Test CSV Export
        export_dir = tmp_path / "exports"
        csv_file, filename, count = await generate_memberships_csv(session, export_dir=export_dir)
        assert csv_file.exists()
        assert count == 3

        csv_text = csv_file.read_text(encoding="utf-8-sig")
        lines = csv_text.splitlines()

        # Check founder timeline progression
        old_line = [l for l in lines if "2025-01-01" in l][0]
        assert ",NO," in old_line

        founder_line = [l for l in lines if "2025-03-01" in l][0]
        assert ",SI," in founder_line

        renew_line = [l for l in lines if "2025-05-01" in l][0]
        assert ",SI," in renew_line

    await engine.dispose()


def test_cleanup_old_backups(tmp_path: Path):
    import os
    import time
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Create 15 dummy backup files with mtime 30 days in the past
    old_timestamp = time.time() - (30 * 86400)
    for i in range(15):
        file = backup_dir / f"backup_202501{i+1:02d}_000000.sql"
        file.write_text(f"DUMMY BACKUP {i}")
        file_time = old_timestamp + i * 100
        os.utime(file, (file_time, file_time))

    # Retain 10 minimum
    deleted = cleanup_old_backups(backup_dir=backup_dir, max_days=14, keep_min=10)
    assert deleted == 5

    remaining = sorted(list(backup_dir.glob("backup_*.sql")))
    assert len(remaining) == 10
