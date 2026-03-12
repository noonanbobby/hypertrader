import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

from app.config import settings
from app.schemas import ServiceCheck, SystemStatus
from app.websocket_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


async def _check_ngrok() -> ServiceCheck:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get("http://127.0.0.1:4040/api/tunnels")
            data = resp.json()
            tunnels = data.get("tunnels", [])
            if tunnels:
                public_url = tunnels[0].get("public_url", "")
                return ServiceCheck(
                    name="ngrok",
                    status="ok",
                    message=f"Tunnel active",
                    url=public_url,
                )
            return ServiceCheck(name="ngrok", status="down", message="No active tunnels")
    except Exception:
        return ServiceCheck(name="ngrok", status="down", message="ngrok not running")


async def _check_telegram() -> ServiceCheck:
    token = settings.telegram_bot_token
    if not settings.telegram_enabled:
        return ServiceCheck(name="telegram", status="degraded", message="Disabled")
    if not token:
        return ServiceCheck(name="telegram", status="degraded", message="No bot token configured")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            if resp.status_code == 200 and resp.json().get("ok"):
                bot_name = resp.json()["result"].get("username", "")
                return ServiceCheck(name="telegram", status="ok", message=f"@{bot_name}")
            return ServiceCheck(name="telegram", status="down", message="Invalid bot token")
    except Exception:
        return ServiceCheck(name="telegram", status="down", message="API unreachable")


def _check_websocket() -> ServiceCheck:
    count = len(ws_manager.active_connections)
    return ServiceCheck(
        name="websocket",
        status="ok" if count > 0 else "degraded",
        message=f"{count} client{'s' if count != 1 else ''} connected",
    )


@router.get("/status", response_model=SystemStatus)
async def get_system_status():
    ngrok_check, telegram_check = await asyncio.gather(
        _check_ngrok(),
        _check_telegram(),
    )
    return SystemStatus(
        backend=ServiceCheck(name="backend", status="ok", message="Running"),
        ngrok=ngrok_check,
        websocket=_check_websocket(),
        telegram=telegram_check,
        checked_at=datetime.now(timezone.utc),
    )
