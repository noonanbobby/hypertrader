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


async def _check_nginx() -> ServiceCheck:
    try:
        import asyncio, subprocess
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", "nginx",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        state = stdout.decode().strip()
        if state == "active":
            return ServiceCheck(name="nginx", status="ok", message="Reverse proxy active")
        return ServiceCheck(name="nginx", status="down", message=f"nginx: {state}")
    except Exception:
        return ServiceCheck(name="nginx", status="down", message="Cannot check nginx")


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
    nginx_check, telegram_check = await asyncio.gather(
        _check_nginx(),
        _check_telegram(),
    )
    return SystemStatus(
        backend=ServiceCheck(name="backend", status="ok", message="Running"),
        ngrok=nginx_check,
        websocket=_check_websocket(),
        telegram=telegram_check,
        checked_at=datetime.now(timezone.utc),
    )
