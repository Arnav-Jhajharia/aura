from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

_pool_kwargs = {"pool_size": 3, "max_overflow": 2} if "sqlite" not in settings.database_url else {}
engine = create_async_engine(settings.database_url, echo=False, **_pool_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
