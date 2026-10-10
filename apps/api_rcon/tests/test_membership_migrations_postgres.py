"""Opt-in Alembic upgrades in an empty, caller-owned disposable PostgreSQL database.

Set MEMBERSHIP_MIGRATION_POSTGRES_TEST_URL to a postgresql+asyncpg URL named
matefield_membership_regression_<suffix>. The caller creates/drops the database;
each case verifies it starts empty and removes only its temporary schema objects.
"""
import asyncio
import hashlib
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import MetaData, and_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


TEMPORARY_DATABASE = re.compile(r"matefield_membership_regression_[a-z0-9_]{8,48}\Z")
HEAD = "r4n5i6j7k8l9"
API_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = API_ROOT.parents[1]
STEAM_ID = "76561198012345678"

# Execute the native CLI after applying the same network restriction in its process.
GUARDED_ALEMBIC = r'''
import os, re, runpy, socket, sys
from sqlalchemy.engine import make_url
url = make_url(os.environ["DATABASE_URL"])
if url.drivername != "postgresql+asyncpg" or not re.fullmatch(
    r"matefield_membership_regression_[a-z0-9_]{8,48}", url.database or ""
):
    raise RuntimeError("Migration subprocess requires an isolated test database")
port = url.port or 5432
allowed = {result[4][0] for result in socket.getaddrinfo(url.host, port, type=socket.SOCK_STREAM)}
def guarded(original):
    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in allowed or address[1] != port:
            raise AssertionError("Migration subprocess cannot contact external services")
        return original(sock, address)
    return connect
socket.socket.connect = guarded(socket.socket.connect)
socket.socket.connect_ex = guarded(socket.socket.connect_ex)
sys.argv = ["alembic", "-c", sys.argv[1], "upgrade", sys.argv[2]]
runpy.run_module("alembic", run_name="__main__")
'''


async def verify_target(connection, expected_database):
    actual = (await connection.execute(text("SELECT current_database()"))).scalar_one()
    assert actual == expected_database and TEMPORARY_DATABASE.fullmatch(actual), "Unsafe migration database"


@pytest_asyncio.fixture
async def migration_database(monkeypatch):
    target = os.environ.get("MEMBERSHIP_MIGRATION_POSTGRES_TEST_URL")
    if not target:
        pytest.skip("Set MEMBERSHIP_MIGRATION_POSTGRES_TEST_URL for isolated Alembic tests")
    url = make_url(target)
    if url.drivername != "postgresql+asyncpg" or not TEMPORARY_DATABASE.fullmatch(url.database or ""):
        pytest.fail("Migration tests require a disposable matefield_membership_regression_ database")
    port = url.port or 5432
    allowed = {result[4][0] for result in socket.getaddrinfo(url.host, port, type=socket.SOCK_STREAM)}

    def guarded(original):
        def connect(sock, address):
            if not isinstance(address, tuple) or address[0] not in allowed or address[1] != port:
                raise AssertionError("Migration tests cannot contact external services")
            return original(sock, address)
        return connect

    monkeypatch.setattr(socket.socket, "connect", guarded(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded(socket.socket.connect_ex))
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    owned = False
    try:
        async with engine.connect() as connection:
            await verify_target(connection, url.database)
            tables = (await connection.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
            ))).all()
            enums = (await connection.execute(text(
                "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                "WHERE t.typtype='e' AND n.nspname=current_schema()"
            ))).all()
            assert not tables and not enums, "The disposable migration database must start empty"
            owned = True
        yield engine, target
    finally:
        try:
            if owned:
                async with engine.begin() as connection:
                    await verify_target(connection, url.database)
                    metadata = MetaData()
                    await connection.run_sync(metadata.reflect)
                    await connection.run_sync(metadata.drop_all)
                    enums = (await connection.execute(text(
                        "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                        "WHERE t.typtype='e' AND n.nspname=current_schema()"
                    ))).scalars().all()
                    for name in enums:
                        identifier = connection.dialect.identifier_preparer.quote(name)
                        await connection.execute(text("DROP TYPE " + identifier))
        finally:
            await engine.dispose()


async def upgrade(target, revision):
    environment = os.environ.copy()
    environment["DATABASE_URL"] = target
    environment["PYTHONPATH"] = os.pathsep.join([
        str(API_ROOT), str(REPOSITORY / "packages/wardogs_config/src"),
        str(REPOSITORY / "packages/wardogs_schemas/src"), environment.get("PYTHONPATH", ""),
    ])
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", GUARDED_ALEMBIC, str(API_ROOT / "alembic.ini"), revision,
        cwd=API_ROOT, env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    output = (stdout + stderr).decode(errors="replace").replace(target, "<test-database-url>")
    password = make_url(target).password
    if password:
        output = output.replace(password, "<redacted>")
    assert process.returncode == 0, "Alembic upgrade failed: " + output


async def reflect(engine):
    metadata = MetaData()
    async with engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    return metadata


def fixture_payloads():
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    return {
        "roles": {"id": 900001, "code": "MIGRATION_TEST", "name": "Migration test", "role_type": "VIP"},
        "players": {"steam_id": STEAM_ID, "discord_id": "777777777777777777", "reward_points": 23,
                    "global_seeding_seconds": 900, "global_rewarded_seconds": 400},
        "membership_types": {"id": 900001, "code": "migration_test", "name": "Migration test",
                             "price_usd": 321, "price_ars": 765432, "default_days": 30,
                             "billing_type": "ONE_TIME", "role_id": 900001, "is_active": True,
                             "created_at": now, "updated_at": now},
        "memberships": {"id": 900001, "steam_id": STEAM_ID, "type": "migration_test",
                        "start_date": now, "end_date": None, "is_active": True, "is_booster": False,
                        "role_granted_id": 900001, "rcon_sync_status": "SUCCESS", "payment_source": "MANUAL",
                        "creation_operation_id": "migration-test-command", "creation_request_hash": "f" * 64,
                        "notified_3d": True, "notified_24h": True},
        "role_discord_bindings": {"id": 900001, "role_id": 900001, "guild_id": "555555555555555555",
                                  "discord_role_id": "666666666666666666", "configured_by": "888888888888888888",
                                  "created_at": now, "updated_at": now},
        "membership_removal_operations": {
            "operation_id": "migration-test-removal", "request_hash": "e" * 64,
            "steam_id": STEAM_ID, "guild_id": "555555555555555555", "actor_id": "888888888888888888",
            "user_id": "777777777777777777", "discord_roles_removed": False, "created_at": now,
            "result_json": json.dumps({
                "ok": True, "steam_id": STEAM_ID, "operation_id": "migration-test-removal",
                "removed_membership_ids": [900000], "replayed": False,
                "discord": {"user_id": "777777777777777777", "guild_id": "555555555555555555",
                            "role_ids": ["666666666666666666"]},
                "warcon": {"status": "SUCCESS", "server_id": "migration-test-server"},
            }),
        },
        "squads": {"id": "migration-test-squad", "name": "Migration squad", "tag": "TEST",
                   "leader_steam_id": STEAM_ID, "created_at": now, "total_kills": 7, "total_deaths": 5,
                   "total_cash_earned": 99, "total_matches_played": 2},
    }


async def seed_and_snapshot(engine, metadata):
    rows = {}
    async with engine.begin() as connection:
        for name, payload in fixture_payloads().items():
            if name not in metadata.tables:
                continue
            table = metadata.tables[name]
            values = {key: value for key, value in payload.items() if key in table.c}
            await connection.execute(table.insert().values(**values))
            predicate = and_(*(column == values[column.name] for column in table.primary_key))
            rows[name] = dict((await connection.execute(select(table).where(predicate))).mappings().one())
    return rows


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_head", [None, "p2l3g4h5i6j7", "0132aeb12a1c", "q3m4h5i6j7k8", "29f437dc92a1"],
                         ids=["fresh", "local-guild-roles", "upstream-squads", "local-cancellation", "upstream-merged"])
async def test_upgrade_preserves_both_membership_histories(migration_database, previous_head):
    engine, target = migration_database
    await upgrade(target, previous_head or "head")
    before_schema = await reflect(engine)
    if previous_head == "p2l3g4h5i6j7":
        assert "squads" not in before_schema.tables
        assert "notified_3d" not in before_schema.tables["memberships"].c
        assert "global_seeding_seconds" not in before_schema.tables["players"].c
    elif previous_head == "0132aeb12a1c":
        assert "role_discord_bindings" not in before_schema.tables
        assert "creation_operation_id" not in before_schema.tables["memberships"].c
        assert "price_ars" not in before_schema.tables["membership_types"].c
    before = await seed_and_snapshot(engine, before_schema)

    await upgrade(target, "head")
    schema = await reflect(engine)
    assert {"role_discord_bindings", "squads", "squad_members", "squad_invites", "membership_removal_operations"}.issubset(schema.tables)
    assert {"creation_operation_id", "creation_request_hash", "notified_3d", "notified_24h"}.issubset(
        schema.tables["memberships"].c.keys())
    assert "price_ars" in schema.tables["membership_types"].c
    assert {"global_seeding_seconds", "global_rewarded_seconds"}.issubset(schema.tables["players"].c.keys())
    assert "server_id" in schema.tables["player_sessions"].c
    after = {}
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all() == [HEAD]
        for name, old_row in before.items():
            table = schema.tables[name]
            predicate = and_(*(column == old_row[column.name] for column in table.primary_key))
            row = (await connection.execute(select(table).where(predicate))).mappings().one()
            after[name] = {key: row[key] for key in old_row}
        if previous_head == "p2l3g4h5i6j7":
            assert (await connection.execute(text(
                "SELECT global_seeding_seconds FROM players WHERE steam_id=:steam"
            ), {"steam": STEAM_ID})).scalar_one() == 0
            assert (await connection.execute(text(
                "SELECT notified_3d FROM memberships WHERE id=900001"
            ))).scalar_one() is False
    assert fingerprint(after) == fingerprint(before), "Upgrade changed existing fixture data"
