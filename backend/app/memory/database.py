"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.memory.models import Base

engine = None
async_session_maker: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    """Create async engine and session maker (call once at startup)."""
    global engine, async_session_maker
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )
    async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def init_db() -> None:
    """Create tables if they do not exist."""
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one request-scoped async session."""
    assert async_session_maker is not None
    async with async_session_maker() as session:
        yield session


def session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the global session maker (for SSE / background tasks)."""
    assert async_session_maker is not None
    return async_session_maker
