"""Live portfolio endpoints — reads directly from Hyperliquid."""

import asyncio
import logging
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas import HLPortfolio, HLPosition, HLFill, HLStatus, WebhookResponse
from app.services.hl_account import hl_account
from app.services.trading_engine import create_engine
from app.services.notification_service import notifier
from app.services.market_data import market_data

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_configured():
    if not hl_account.is_configured():
        raise HTTPException(status_code=400, detail="Hyperliquid credentials not configured")


@router.get("/live/status", response_model=HLStatus)
async def live_status():
    """Check if HL is configured and reachable."""
    if not hl_account.is_configured():
        return HLStatus(configured=False, connected=False, account_value=None)
    try:
        portfolio = await hl_account.get_portfolio()
        return HLStatus(
            configured=True,
            connected=True,
            account_value=portfolio["account_value"],
        )
    except Exception as e:
        logger.warning("HL connection check failed: %s", e)
        return HLStatus(configured=True, connected=False, account_value=None)


@router.get("/live/portfolio", response_model=HLPortfolio)
async def live_portfolio():
    """Get HL account portfolio summary."""
    _require_configured()
    try:
        data = await hl_account.get_portfolio()
        return HLPortfolio(**data)
    except Exception as e:
        logger.exception("Failed to get portfolio")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/live/positions", response_model=list[HLPosition])
async def live_positions():
    """Get open positions from HL."""
    _require_configured()
    try:
        positions = await hl_account.get_open_positions()
        return [HLPosition(**p) for p in positions]
    except Exception as e:
        logger.exception("Failed to get positions")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/live/fills", response_model=list[HLFill])
async def live_fills():
    """Get recent fills from HL."""
    _require_configured()
    try:
        fills = await hl_account.get_recent_fills()
        return [HLFill(**f) for f in fills]
    except Exception as e:
        logger.exception("Failed to get fills")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/live/positions/{symbol}/close", response_model=WebhookResponse)
async def close_live_position(symbol: str):
    """Close a live position — delegates to position tracking system."""
    _require_configured()
    from app.database import async_session
    from app.routers.position_tracking import close_position as _close_pos
    from app.database import get_db

    coin = market_data.normalize_coin(symbol)
    try:
        async with async_session() as db:
            result = await _close_pos(coin, db=db)
            return WebhookResponse(success=result.success, message=result.message)
    except HTTPException as e:
        return WebhookResponse(success=False, message=e.detail)
    except Exception as e:
        logger.exception("Failed to close live position %s", symbol)
        return WebhookResponse(success=False, message=str(e))
