import asyncio
import datetime as dt
import os
import tempfile
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
async def setup():
    """Spin up a temp-file DB, create tables, patch all refs, yield (client, price_mock, sz_mock)."""

    # --- Temp-file SQLite (avoids in-memory sharing issues with aiosqlite) ---
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )

    # --- Create all tables (import models first so they register with Base) ---
    from app.database import Base
    import app.models  # noqa: F401 — registers models with Base.metadata
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # --- Seed AppSettings row ---
    from app.models import AppSettings
    async with test_session_factory() as db:
        row = AppSettings(
            id=1,
            trading_mode="paper",
            webhook_secret="test-secret",
            leverage=10.0,
            initial_balance=10000.0,
            slippage_pct=0.0,
            taker_fee_pct=0.05,
            maker_fee_pct=0.02,
            use_limit_orders=False,
            limit_order_timeout_sec=30.0,
            limit_order_offset_pct=0.0,
            default_max_position_pct=25.0,
            default_max_drawdown_pct=10.0,
            default_daily_loss_limit=500.0,
            telegram_enabled=False,
            telegram_bot_token="",
            telegram_chat_id="",
            telegram_chat_id_2="",
            notify_trade_open=False,
            notify_trade_close=False,
            notify_risk_breach=False,
            updated_at=dt.datetime.utcnow(),
        )
        db.add(row)
        await db.commit()

    # --- Configure in-memory settings ---
    from app.config import settings
    settings.trading_mode = "paper"
    settings.webhook_secret = "test-secret"
    settings.leverage = 10.0
    settings.initial_balance = 10000.0
    settings.slippage_pct = 0.0
    settings.taker_fee_pct = 0.05
    settings.maker_fee_pct = 0.02
    settings.use_limit_orders = False
    settings.telegram_enabled = False
    settings.notify_trade_open = False
    settings.notify_trade_close = False
    settings.notify_risk_breach = False
    settings.default_max_position_pct = 25.0
    settings.default_max_drawdown_pct = 10.0
    settings.default_daily_loss_limit = 500.0

    # --- Mocks ---
    price_mock = AsyncMock(return_value=100000.0)
    sz_decimals_mock = AsyncMock(return_value=5)

    from app.services.market_data import market_data

    # --- Patch DB refs + market data ---
    with (
        patch("app.database.engine", test_engine),
        patch("app.database.async_session", test_session_factory),
        patch("app.main.async_session", test_session_factory),
        patch("app.routers.webhook.async_session", test_session_factory),
        patch.object(market_data, "get_mid_price", price_mock),
        patch.object(market_data, "get_sz_decimals", sz_decimals_mock),
    ):
        from app.main import app
        from app.database import get_db

        async def override_get_db():
            async with test_session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db

        # Clear webhook locks from previous tests
        from app.routers.webhook import _webhook_locks
        _webhook_locks.clear()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client, price_mock, sz_decimals_mock

        app.dependency_overrides.clear()

    await test_engine.dispose()
    os.unlink(db_path)


def _webhook(action, symbol="BTCUSDT", strategy="test", **kwargs):
    """Build a webhook payload dict.

    Default size_pct=2.0 keeps notional ($2000) within the 25% risk limit.
    """
    payload = {
        "secret": "test-secret",
        "strategy": strategy,
        "action": action,
        "symbol": symbol,
        "size_pct": 2.0,
        "message": "",
    }
    payload.update(kwargs)
    return payload
