"""データベース接続・セッション管理モジュール。"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

logger = logging.getLogger(__name__)

# Build engine kwargs based on the backend type.
# asyncpg (PostgreSQL) and aiosqlite (SQLite) have different requirements.
_engine_kwargs: dict = {"echo": settings.debug}
if settings.is_sqlite:
    # SQLite requires check_same_thread=False for async use
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL / asyncpg connection pool settings
    _engine_kwargs.update({
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
    })

try:
    engine = create_async_engine(settings.database_url_normalized, **_engine_kwargs)
    logger.info("DB engine created: %s", settings.database_url_normalized.split("@")[-1])
except Exception as _exc:  # noqa: BLE001
    # Fall back to in-memory SQLite so the app can still start if the
    # primary database is misconfigured.  Errors will be visible in the logs.
    logger.error(
        "DB engine creation failed (%s) — falling back to SQLite: %s",
        type(_exc).__name__,
        _exc,
    )
    engine = create_async_engine(
        "sqlite+aiosqlite:///./ocr-fallback.db",
        connect_args={"check_same_thread": False},
        echo=settings.debug,
    )

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
