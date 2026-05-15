"""
Database — Async SQLAlchemy engine + session.

Usage:
    from backend.app.database import get_session, engine

    async with get_session() as session:
        result = await session.execute(select(LegalDocument))
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# Async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=5,
    max_overflow=10,
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class cho tất cả ORM models."""
    pass


async def get_session() -> AsyncSession:
    """Dependency injection cho FastAPI."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Tạo tất cả tables (dùng trong development, production dùng Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
