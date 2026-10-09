import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine('postgresql+asyncpg://matefield_user:matefield_password@localhost:5432/matefield_db', echo=False)

async def m():
    async with engine.connect() as c:
        r = await c.execute(text("SELECT data_type FROM information_schema.columns WHERE table_name='bot_config' AND column_name='config_value'"))
        print(r.scalar())

if __name__ == '__main__':
    asyncio.run(m())
