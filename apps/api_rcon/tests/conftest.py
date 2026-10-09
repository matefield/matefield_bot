import sys
from pathlib import Path

api_rcon_root = Path(__file__).resolve().parent.parent
api_rcon_src = api_rcon_root / "src"
if str(api_rcon_root) not in sys.path:
    sys.path.insert(0, str(api_rcon_root))

try:
    import src
    if hasattr(src, "__path__") and str(api_rcon_src) not in src.__path__:
        src.__path__.insert(0, str(api_rcon_src))
except ImportError:
    pass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Ensure we import the FastAPI app from api_rcon
if "src.main" in sys.modules and not hasattr(sys.modules["src.main"], "app"):
    del sys.modules["src.main"]

from src.connections.apis.rcon import RCONManager
from src.connections.databases.db import get_session
from src.main import app
from src.security.guard import verify_api_key_guard

TEST_SQLITE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        TEST_SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(test_engine, expire_on_commit=False) as sess:
        yield sess

    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest_asyncio.fixture
async def client(session):
    async def override_get_session():
        yield session

    def override_verify_guard():
        return True

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[verify_api_key_guard] = override_verify_guard

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(verify_api_key_guard, None)


@pytest.fixture(autouse=True)
def reset_rcon_pool():
    RCONManager.reset_pool()
    yield
    RCONManager.reset_pool()
