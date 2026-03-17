"""Periodic equity snapshot service.

Records account equity every hour for the analytics equity curve.
Uses strategy_id=0 for live mode snapshots.
"""

import asyncio
import logging
import datetime as dt

from app.database import async_session
from app.models import EquitySnapshot

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = 3600  # 1 hour


async def equity_snapshot_loop():
    """Background task: take an equity snapshot every hour."""
    # Wait for startup
    await asyncio.sleep(60)

    while True:
        try:
            await _take_snapshot()
        except Exception:
            logger.exception("Equity snapshot failed")
        await asyncio.sleep(SNAPSHOT_INTERVAL)


async def _take_snapshot():
    """Take a single equity snapshot from Hyperliquid account."""
    from app.config import settings

    if not settings.hl_api_key or not settings.hl_api_secret:
        return

    try:
        from app.services.hl_account import hl_account
        state = await hl_account.get_account_state()
        if not state:
            return

        account_value = float(state.get("marginSummary", {}).get("accountValue", 0))
        if account_value <= 0:
            return

        # Calculate drawdown from peak
        # We'll track peak in the snapshots themselves
        async with async_session() as db:
            # Get peak equity from previous snapshots
            from sqlalchemy import select, func
            result = await db.execute(
                select(func.max(EquitySnapshot.equity)).where(
                    EquitySnapshot.strategy_id == 0
                )
            )
            peak = result.scalar() or account_value
            peak = max(peak, account_value)

            drawdown = 0.0
            if peak > 0:
                drawdown = round((peak - account_value) / peak * 100, 2)

            snapshot = EquitySnapshot(
                strategy_id=0,
                equity=round(account_value, 2),
                drawdown=drawdown,
                timestamp=dt.datetime.utcnow(),
            )
            db.add(snapshot)
            await db.commit()
            logger.info(
                "Equity snapshot: $%.2f (drawdown: %.2f%%)",
                account_value, drawdown,
            )
    except Exception:
        logger.exception("Failed to take equity snapshot")
