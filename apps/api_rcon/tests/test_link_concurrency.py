import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import Player
from src.modules.v1.schemas.dtos import LinkAccountRequest
from src.modules.v1.services.players_service import PlayersService

A, B = "123456789012345678", "223456789012345678"
S, T = "76561198000000888", "76561198000000999"

@pytest.mark.asyncio
async def test_link_account_is_idempotent_and_rejects_replacement(session):
    first = await PlayersService.link_account(LinkAccountRequest(discord_id=A, steam_id=S), session)
    again = await PlayersService.link_account(LinkAccountRequest(discord_id=A, steam_id=S), session)
    assert first["already_linked"] is False and again["already_linked"] is True
    for discord_id, steam_id in [(A, T), (B, S)]:
        with pytest.raises(HTTPException):
            await PlayersService.link_account(LinkAccountRequest(discord_id=discord_id, steam_id=steam_id), session)
    assert (await session.get(Player, S)).discord_id == A
    assert await session.get(Player, T) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_player,same_pair,same_discord", [
    (True, False, False), (False, False, False), (False, True, True), (False, False, True)
])
async def test_concurrent_link_requests_keep_one_mapping(tmp_path, existing_player, same_pair, same_discord):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "race.db"))
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    if existing_player:
        async with AsyncSession(engine) as session:
            session.add(Player(steam_id=S))
            await session.commit()
    async def link(discord_id, steam_id):
        async with AsyncSession(engine) as session:
            try:
                return await PlayersService.link_account(LinkAccountRequest(discord_id=discord_id, steam_id=steam_id), session)
            except HTTPException as exc:
                return exc.status_code
    try:
        results = await asyncio.gather(link(A, S), link(A if same_discord else B, S if same_pair or not same_discord else T))
        async with AsyncSession(engine) as session:
            linked = (await session.exec(select(Player).where(Player.discord_id.is_not(None)))).all()
            assert len(linked) == 1
        if same_pair:
            assert all(isinstance(r, dict) and r["ok"] for r in results)
            assert sum(bool(r["already_linked"]) for r in results) == 1
        else:
            assert sum(isinstance(r, dict) for r in results) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_consumed_link_and_mapping_commit_atomically_under_race(tmp_path):
    from src.connections.databases.db import SteamLinkRedemption
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "redemption.db"))
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async def redeem(steam):
        async with AsyncSession(engine) as session:
            try:
                return await PlayersService.link_account(
                    LinkAccountRequest(discord_id=A, steam_id=steam), session,
                    redemption=SteamLinkRedemption(token_hash="same-signed-link", expires_at=9999999999))
            except HTTPException as exc:
                return exc.status_code
    try:
        results = await asyncio.gather(redeem(S), redeem(T))
        assert sum(isinstance(result, dict) for result in results) == 1
        async with AsyncSession(engine) as session:
            assert len((await session.exec(select(SteamLinkRedemption))).all()) == 1
            assert len((await session.exec(select(Player).where(Player.discord_id == A))).all()) == 1
    finally:
        await engine.dispose()
