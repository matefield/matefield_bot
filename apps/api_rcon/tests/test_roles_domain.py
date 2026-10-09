
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from src.connections.databases.db import Role, RoleType

sqlite_url = "sqlite+aiosqlite:///test_domain.db"
engine = create_async_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with AsyncSession(engine) as session:
        yield session

@pytest.mark.asyncio
async def test_role_creation_and_types(session: AsyncSession):
    """Test creating roles with new RoleType enum"""
    
    # Arrange
    admin_role = Role(
        code="OWNER_MAIN",
        name="Dueo Principal",
        discord_role_id="123456789",
        role_type=RoleType.SYSTEM
    )
    
    vip_role = Role(
        code="VIP_EXPRESS",
        name="VIP Express (15 dias)",
        discord_role_id="987654321",
        role_type=RoleType.VIP
    )
    
    # Act
    session.add(admin_role)
    session.add(vip_role)
    await session.commit()
    
    # Assert
    roles = (await session.exec(select(Role))).all()
    assert len(roles) == 2
    
    db_admin = (await session.exec(select(Role).where(Role.code == "OWNER_MAIN"))).first()
    assert db_admin is not None
    assert db_admin.role_type == RoleType.SYSTEM
    assert db_admin.name == "Dueo Principal"
    
    db_vip = (await session.exec(select(Role).where(Role.code == "VIP_EXPRESS"))).first()
    assert db_vip is not None
    assert db_vip.role_type == RoleType.VIP
