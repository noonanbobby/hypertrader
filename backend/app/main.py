import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings, RUNTIME_FIELDS, _env_settings
from app.version import __version__
from app.database import init_db, async_session
from app.models import AppSettings
from app.websocket_manager import ws_manager
from app.services.pnl_broadcaster import pnl_broadcast_loop
from app.services.equity_snapshotter import equity_snapshot_loop
from app.routers import webhook, strategies, trades, positions, dashboard, analytics, settings as settings_router, status, live, assets, position_tracking

import datetime as dt


async def seed_settings():
    """Create or load app_settings row. First run seeds from .env."""
    async with async_session() as db:
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            row = AppSettings(
                id=1,
                **{field: getattr(_env_settings, field) for field in RUNTIME_FIELDS},
                updated_at=dt.datetime.utcnow(),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        settings.update_from_db_row(row)


async def sync_position_tracking():
    """Sync position_tracking table with actual Hyperliquid positions on startup."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        from app.services.hl_account import hl_account
        from app.models import PositionTracking
        if not hl_account.is_configured():
            return
        hl_positions = await hl_account.get_open_positions()
        async with async_session() as db:
            for pos in hl_positions:
                coin = pos["symbol"]
                result = await db.execute(
                    select(PositionTracking).where(PositionTracking.coin == coin)
                )
                pt = result.scalar_one_or_none()
                if pt is None:
                    logger.warning("UNTRACKED position found on %s — syncing from Hyperliquid", coin)
                    pt = PositionTracking(
                        coin=coin,
                        direction=pos["side"],
                        signal_size=pos["notional"],
                        manual_size=0.0,
                        total_size=pos["notional"],
                        entry_price=pos["entry_price"],
                        opened_at=dt.datetime.utcnow(),
                        origin="reconciler",
                        last_modified_at=dt.datetime.utcnow(),
                        last_modified_by="reconciler",
                    )
                    db.add(pt)
                elif not pt.direction:
                    logger.warning("STALE tracking for %s (was flat, now %s) — syncing", coin, pos["side"])
                    pt.direction = pos["side"]
                    pt.signal_size = pos["notional"]
                    pt.manual_size = 0.0
                    pt.total_size = pos["notional"]
                    pt.entry_price = pos["entry_price"]
                    pt.opened_at = dt.datetime.utcnow()
                    pt.origin = "reconciler"
                    pt.last_modified_at = dt.datetime.utcnow()
                    pt.last_modified_by = "reconciler"

            # Also ensure all enabled assets have a tracking record
            from app.models import AssetConfig
            assets_result = await db.execute(select(AssetConfig))
            for asset in assets_result.scalars().all():
                pt_result = await db.execute(
                    select(PositionTracking).where(PositionTracking.coin == asset.coin)
                )
                if pt_result.scalar_one_or_none() is None:
                    db.add(PositionTracking(coin=asset.coin))

            await db.commit()
            logger.info("Position tracking synced with Hyperliquid")
    except Exception as e:
        logger.warning("Failed to sync position tracking: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_settings()
    await sync_position_tracking()
    pnl_task = asyncio.create_task(pnl_broadcast_loop())
    equity_task = asyncio.create_task(equity_snapshot_loop())
    yield
    pnl_task.cancel()
    equity_task.cancel()
    try:
        await pnl_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="HyperTrader",
    description="Trading bot with TradingView webhooks and Hyperliquid execution",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "http://localhost:3001",
        "http://35.72.135.92",
        "http://35.72.135.92:3000",
        "http://35.72.135.92:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(webhook.router, prefix="/api", tags=["webhook"])
app.include_router(strategies.router, prefix="/api", tags=["strategies"])
app.include_router(trades.router, prefix="/api", tags=["trades"])
app.include_router(positions.router, prefix="/api", tags=["positions"])
app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
app.include_router(analytics.router, prefix="/api", tags=["analytics"])
app.include_router(settings_router.router, prefix="/api", tags=["settings"])
app.include_router(status.router, prefix="/api", tags=["status"])
app.include_router(live.router, prefix="/api", tags=["live"])
app.include_router(assets.router, prefix="/api", tags=["assets"])
app.include_router(position_tracking.router, prefix="/api", tags=["position_tracking"])


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "mode": settings.trading_mode,
        "version": __version__,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await ws_manager.send_personal(websocket, "pong", {})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
