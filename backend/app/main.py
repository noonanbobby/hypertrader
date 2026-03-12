from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings, RUNTIME_FIELDS, _env_settings
from app.version import __version__
from app.database import init_db, async_session
from app.models import AppSettings
from app.websocket_manager import ws_manager
from app.routers import webhook, strategies, trades, positions, dashboard, analytics, settings as settings_router, status

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_settings()
    yield


app = FastAPI(
    title="HyperTrader",
    description="Trading bot with TradingView webhooks and Hyperliquid execution",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
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
