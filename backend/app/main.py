from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.websocket_manager import ws_manager
from app.routers import webhook, strategies, trades, positions, dashboard, analytics


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="HyperTrader",
    description="Trading bot with TradingView webhooks and Hyperliquid execution",
    version="1.0.0",
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


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "mode": settings.trading_mode,
        "version": "1.0.0",
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Client can send ping/pong or subscribe messages
            if data == "ping":
                await ws_manager.send_personal(websocket, "pong", {})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
