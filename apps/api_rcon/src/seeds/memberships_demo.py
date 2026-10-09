"""Create fictional memberships without starting the API or its sync workers.

Run from apps/api_rcon with APP_ENV=local:
    uv run python -m src.seeds.memberships_demo

Existing catalog settings and demo records are preserved. Active RCON servers
are rejected because the regular maintenance worker would sync active demos.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Membership, MembershipType, Player, RconServer, engine
from wardogs_config import ENVIRONMENT_SETTINGS


_TYPES = (
    ("express", "VIP_EXPRESS", "VIP EXPRESS", "Prioridad de conexión y rol VIP EXPRESS por 14 días", 14, 300, 500000),
    ("regular", "VIP_COMUN", "VIP NORMAL", "Prioridad de conexión y rol VIP por 30 días", 30, 500, 700000),
    ("permanent", "VIP_PERMANENTE", "VIP Permanente", None, 0, 0, None),
    ("seed", "VIP_SEED", "VIP por seeding", None, 15, 0, None),
)


async def seed_memberships(
    session: AsyncSession, now: datetime | None = None
) -> dict[str, int]:
    """Atomically add missing fixtures, leaving any caller transaction open."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    now = now.replace(microsecond=0)
    counts = {
        "types_created": 0,
        "players_created": 0,
        "memberships_created": 0,
        "memberships_existing": 0,
    }
    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    async with transaction:
        active_server = (
            await session.exec(select(RconServer.id).where(RconServer.is_active == True))
        ).first()
        if active_server is not None:
            raise RuntimeError("Demo seeding requires a database without active RCON servers.")

        catalog = (await session.exec(select(MembershipType))).all()
        by_code = {item.code.casefold(): item for item in catalog}
        for type_index, (code, legacy_code, name, description, default_days, price_usd, price_ars) in enumerate(_TYPES):
            membership_type = by_code.get(code) or by_code.get(legacy_code.casefold())
            if membership_type is None:
                membership_type = MembershipType(
                    code=code,
                    name=name,
                    description=description,
                    price_usd=price_usd,
                    price_ars=price_ars,
                    default_days=default_days,
                    is_active=True,
                )
                session.add(membership_type)
                by_code[code] = membership_type
                counts["types_created"] += 1

            duration = membership_type.default_days
            if duration < 0:
                raise RuntimeError("Demo membership durations must not be negative.")
            cases = _permanent_cases() if code == "permanent" else _timed_cases(duration)
            for index, (offset, is_active, is_booster) in enumerate(cases, start=1):
                steam_id = f"demo-{code}-{index:02d}"
                player = await session.get(Player, steam_id)
                if player is None:
                    session.add(Player(steam_id=steam_id, in_game_name=f"Demo {code} {index:02d}"))
                    counts["players_created"] += 1
                    await session.flush()

                existing = (
                    await session.exec(select(Membership.id).where(Membership.steam_id == steam_id))
                ).first()
                if existing is not None:
                    counts["memberships_existing"] += 1
                    continue

                fixture_now = now - timedelta(seconds=type_index * 10 + index - 1)
                if code == "permanent" or duration == 0:
                    start_date = fixture_now - timedelta(days=offset) if code == "permanent" else fixture_now
                    end_date = None
                else:
                    end_date = fixture_now + timedelta(days=offset)
                    start_date = end_date - timedelta(days=duration)

                session.add(Membership(
                    steam_id=steam_id,
                    membership_type=membership_type.code,
                    start_time=start_date,
                    end_time=end_date,
                    is_active=is_active,
                    is_booster=is_booster,
                    payment_source="REWARDS" if code == "seed" else "MANUAL",
                ))
                counts["memberships_created"] += 1
        await session.flush()
    return counts


def _timed_cases(duration: int) -> tuple[tuple[int, bool, bool], ...]:
    return (
        (duration, True, False),
        (min(duration, 7), True, False),
        (min(duration, 1), True, False),
        (0, False, False),
        (-1, False, False),
        (-duration, False, False),
        (min(duration, 5), False, False),
        (min(duration, 3), True, True),
        (-3, False, True),
        (min(duration, 1), False, True),
    )


def _permanent_cases() -> tuple[tuple[int, bool, bool], ...]:
    return (
        (0, True, False),
        (180, True, False),
        (365, True, True),
        (90, False, False),
        (30, False, True),
    )


def validate_local_target(environment: str, database_url: str, rcon_url: str) -> None:
    """Check configured destinations without exposing connection credentials."""
    if environment.strip().lower() not in {"local", "test", "dev"}:
        raise RuntimeError("Set APP_ENV=local, test or dev explicitly to run demo seeding.")
    try:
        database_host = (make_url(database_url).host or "").lower()
        rcon_host = (urlsplit(rcon_url).hostname or "").lower()
    except (ValueError, SQLAlchemyError):
        raise RuntimeError("Demo seeding requires valid local database and RCON URLs.") from None
    loopback = {"localhost", "127.0.0.1", "::1"}
    if database_host not in loopback | {"postgres", "matefield_db_local"}:
        raise RuntimeError("Demo seeding requires a local database host.")
    is_mock = re.fullmatch(r"mock[-_]rcon(?:[-_][a-z0-9]+)?", rcon_host) is not None
    if rcon_host not in loopback and not is_mock:
        raise RuntimeError("Demo seeding requires a mock or loopback fallback RCON host.")


async def main() -> None:
    connections = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    validate_local_target(
        os.environ.get("APP_ENV", ""), connections.DATABASE_URL, connections.RCON_URL
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            counts = await seed_memberships(session)
        print(json.dumps(counts, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except SQLAlchemyError:
        raise SystemExit("Demo seeding failed; no fixtures were committed.") from None
