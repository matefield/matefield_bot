import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Role, RoleType

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
