import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def _migrate_columns(conn):
    """Add missing columns to existing tables (never deletes data)."""
    migrations = [
        ("app_settings", "telegram_enabled", "BOOLEAN DEFAULT 0"),
        ("app_settings", "telegram_bot_token", "VARCHAR(255) DEFAULT ''"),
        ("app_settings", "telegram_chat_id", "VARCHAR(255) DEFAULT ''"),
        ("app_settings", "telegram_chat_id_2", "VARCHAR(255) DEFAULT ''"),
        ("app_settings", "default_size_pct", "FLOAT DEFAULT 10.0"),
        ("app_settings", "notify_trade_open", "BOOLEAN DEFAULT 1"),
        ("app_settings", "notify_trade_close", "BOOLEAN DEFAULT 1"),
        ("app_settings", "notify_risk_breach", "BOOLEAN DEFAULT 1"),
        ("app_settings", "trading_paused", "BOOLEAN DEFAULT 0"),
        ("app_settings", "use_max_size", "BOOLEAN DEFAULT 0"),
        ("app_settings", "webhook_url", "VARCHAR(500) DEFAULT ''"),
    ]
    for table, column, col_type in migrations:
        try:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            )
            logger.info(f"Added column {table}.{column}")
        except Exception:
            pass  # Column already exists


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_columns(conn)
