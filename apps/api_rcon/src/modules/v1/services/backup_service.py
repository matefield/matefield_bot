import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy import text
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from wardogs_config import ENVIRONMENT_SETTINGS

logger = logging.getLogger("wardogs.backup")


def get_backup_dir(base_dir: Path | str | None = None) -> Path:
    """Returns the backup directory as a resolved Path, creating it if needed."""
    if base_dir:
        path = Path(base_dir)
    else:
        path = Path(ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.BACKUP_DIR)
    
    path.mkdir(parents=True, exist_ok=True)
    return path


def _escape_sql_value(val: Any) -> str:
    """Formats a Python value as a standard SQL literal."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'"
    val_str = str(val).replace("'", "''")
    return f"'{val_str}'"


async def create_database_sql_backup(
    session: AsyncSession,
    backup_dir: Path | str | None = None
) -> Path:
    """
    Dumps the full PostgreSQL database into a system-compatible SQL file
    in backup_dir (backup_<timestamp>.sql) and updates latest.sql.
    Enforces the retention policy after creation.
    """
    target_dir = get_backup_dir(backup_dir)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    sql_file = target_dir / f"backup_{timestamp}.sql"

    sorted_tables = SQLModel.metadata.sorted_tables

    sql_lines: list[str] = [
        "-- --------------------------------------------------------",
        "-- Matefield Database SQL Backup",
        f"-- Generated at: {datetime.now(UTC).isoformat()}",
        "-- --------------------------------------------------------",
        "BEGIN;",
        ""
    ]

    conn = await session.connection()

    # 1. Handle alembic_version if exists
    try:
        alembic_res = (await conn.execute(text("SELECT version_num FROM alembic_version"))).fetchall()
        if alembic_res:
            sql_lines.append("-- Table: alembic_version")
            sql_lines.append("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL);")
            for row in alembic_res:
                v = row[0] if isinstance(row, (tuple, list)) else getattr(row, "version_num", str(row))
                sql_lines.append(f"INSERT INTO alembic_version (version_num) VALUES ({_escape_sql_value(v)});")
            sql_lines.append("")
    except Exception as e:
        logger.debug(f"Could not dump alembic_version: {e}")

    # 2. Dump all registered SQLModel tables in topological dependency order
    for table in sorted_tables:
        table_name = table.name
        columns = [c.name for c in table.columns]

        query = sa_select(table)
        result = (await conn.execute(query)).fetchall()

        sql_lines.append(f"-- Table: {table_name}")
        if result:
            cols_quoted = ", ".join([f'"{col}"' for col in columns])
            for row in result:
                row_map = row._mapping
                values = [row_map.get(col) for col in columns]
                vals_escaped = ", ".join([_escape_sql_value(v) for v in values])
                sql_lines.append(f'INSERT INTO "{table_name}" ({cols_quoted}) VALUES ({vals_escaped});')
        sql_lines.append("")

    sql_lines.append("COMMIT;")
    sql_lines.append("")

    sql_file.write_text("\n".join(sql_lines), encoding="utf-8")

    # Update latest.sql copy
    latest_sql = target_dir / "latest.sql"
    try:
        shutil.copyfile(sql_file, latest_sql)
    except Exception as e:
        logger.warning(f"Could not update latest.sql copy: {e}")

    # Enforce retention policy (thresholds configurable via BACKUP_RETENTION_DAYS / BACKUP_KEEP_MIN)
    cfg = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    cleanup_old_backups(target_dir, max_days=cfg.BACKUP_RETENTION_DAYS, keep_min=cfg.BACKUP_KEEP_MIN)

    logger.info(f"[Backup] Successfully generated SQL backup: {sql_file.name} ({sql_file.stat().st_size} bytes)")
    return sql_file


def cleanup_old_backups(
    backup_dir: Path,
    max_days: int = 14,
    keep_min: int = 10
) -> int:
    """Removes timestamped SQL backups older than max_days while keeping at least keep_min."""
    deleted_count = 0
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=max_days)

    files = sorted(backup_dir.glob("backup_*.sql"), key=lambda p: p.stat().st_mtime)
    while len(files) > keep_min:
        oldest = files[0]
        mtime = datetime.fromtimestamp(oldest.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            try:
                oldest.unlink()
                deleted_count += 1
                files.pop(0)
            except Exception as e:
                logger.warning(f"Could not delete old backup {oldest}: {e}")
                break
        else:
            break

    return deleted_count
