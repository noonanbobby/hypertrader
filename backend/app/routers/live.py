"""Live portfolio endpoints — reads directly from Hyperliquid."""

import logging
from fastapi import APIRouter

from app.schemas import HLPortfolio, HLPosition, HLFill, HLStatus
from app.services.hl_account import hl_account

logger = logging.getLogger(__name__)

router = APIRouter()


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
    data = await hl_account.get_portfolio()
    return HLPortfolio(**data)


@router.get("/live/positions", response_model=list[HLPosition])
async def live_positions():
    """Get open positions from HL."""
    positions = await hl_account.get_open_positions()
    return [HLPosition(**p) for p in positions]


@router.get("/live/fills", response_model=list[HLFill])
async def live_fills():
    """Get recent fills from HL."""
    fills = await hl_account.get_recent_fills()
    return [HLFill(**f) for f in fills]
