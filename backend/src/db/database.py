"""データベース接続・セッション管理モジュール。"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

_engine_kwargs: dict = {"echo": settings.debug}
if not settings.is_sqlite:
    # PostgreSQL supports connection pooling; SQLite does not
    _engine_kwargs.update({"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20})
else:
    # SQLite requires check_same_thread=False for async use
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(settings.database_url_normalized, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """全モデルの基底クラス。"""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依存性注入用 DB セッションジェネレーター。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    """アプリ起動時にテーブルを作成する。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
