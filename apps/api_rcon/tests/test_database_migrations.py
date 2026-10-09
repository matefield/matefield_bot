"""The Docker entrypoint must be able to resolve `alembic upgrade head`."""
from pathlib import Path

from alembic.script import ScriptDirectory


def test_database_migrations_have_one_resolvable_head():
    migrations = Path(__file__).resolve().parents[1] / "src/connections/databases/migrations"
    script = ScriptDirectory(str(migrations))
    assert script.get_current_head() is not None
    assert list(script.walk_revisions())
