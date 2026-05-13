import os
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .models import Base

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        db_path = os.getenv("DB_PATH", "cryptorg_bot.db")
        url = URL.create(drivername="sqlite+aiosqlite", database=db_path)
        _engine = create_async_engine(url, echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db():
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session
