from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from workassistant.config import DATABASE_URL
from workassistant.models.base import Base

async_engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(async_engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    await async_engine.dispose()
