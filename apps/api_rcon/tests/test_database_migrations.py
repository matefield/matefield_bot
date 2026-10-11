"""The Docker entrypoint can upgrade fresh installs and production backups."""
from pathlib import Path

from alembic.script import ScriptDirectory


def migrations():
    root = Path(__file__).resolve().parents[1] / "src/connections/databases/migrations"
    return ScriptDirectory(str(root))


def test_database_migrations_have_one_resolvable_head():
    script = migrations()
    assert script.get_current_head() == "u7q8l9m0n1o2"
    assert list(script.walk_revisions())


def test_production_notification_history_has_an_upgrade_path():
    script = migrations()
    assert script.get_revision("0132aeb12a1c").down_revision == "n0j1e2f3g4h5"
    assert script.get_revision("n0j1e2f3g4h5").down_revision == "8f56df8b4ac3"
    assert script.get_revision("7bd48ca30901").down_revision == "2c236beea135"
    assert list(script.iterate_revisions("head", "0132aeb12a1c"))
