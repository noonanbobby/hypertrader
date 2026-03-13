import asyncio
import logging

from sqlalchemy import select

from app.database import async_session
from app.models import Position
from app.config import settings
from app.services.market_data import market_data
from app.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

INTERVAL = 1.5
ERROR_INTERVAL = 5.0


async def pnl_broadcast_loop():
    """Background loop: fetch prices and push unrealized P&L over WebSocket."""
    while True:
        try:
            # Skip if nobody is listening
            if not ws_manager.active_connections:
                await asyncio.sleep(INTERVAL)
                continue

            # Load open positions from DB
            async with async_session() as db:
                result = await db.execute(select(Position))
                positions = result.scalars().all()

            if not positions:
                await asyncio.sleep(INTERVAL)
                continue

            # Single API call for all mid prices
            mids = await market_data.get_all_mids()
            if not mids:
                await asyncio.sleep(ERROR_INTERVAL)
                continue

            leverage = settings.leverage
            updates = []

            for pos in positions:
                coin = market_data.normalize_coin(pos.symbol)
                price = mids.get(coin)
                if price is None:
                    continue

                notional = price * pos.quantity
                margin = pos.entry_price * pos.quantity / leverage

                if pos.side == "long":
                    pnl = (price - pos.entry_price) * pos.quantity
                else:
                    pnl = (pos.entry_price - price) * pos.quantity

                pnl_pct = round((pnl / margin * 100) if margin > 0 else 0.0, 2)

                updates.append({
                    "id": pos.id,
                    "current_price": round(price, 6),
                    "unrealized_pnl": round(pnl, 4),
                    "pnl_pct": pnl_pct,
                    "notional_value": round(notional, 2),
                })

            if updates:
                await ws_manager.broadcast("pnl_update", updates)

            await asyncio.sleep(INTERVAL)

        except asyncio.CancelledError:
            logger.info("P&L broadcaster shutting down")
            return
        except Exception:
            logger.exception("P&L broadcast error, backing off")
            await asyncio.sleep(ERROR_INTERVAL)
