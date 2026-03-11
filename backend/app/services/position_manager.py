import datetime as dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Position, Trade, Strategy, TradeStatus
from app.services.market_data import market_data
from app.websocket_manager import ws_manager


class PositionManager:
    async def open_position(
        self,
        db: AsyncSession,
        strategy_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        fees: float,
        message: str = "",
    ) -> tuple[Position, Trade]:
        """Open a new position and record the entry trade."""
        # Check for existing position in same symbol/strategy
        existing = await self._get_position(db, strategy_id, symbol)
        if existing:
            # Add to existing position (average in)
            total_qty = existing.quantity + quantity
            avg_price = (
                (existing.entry_price * existing.quantity + entry_price * quantity)
                / total_qty
            )
            existing.entry_price = round(avg_price, 6)
            existing.quantity = total_qty
            existing.updated_at = dt.datetime.utcnow()
            position = existing
        else:
            position = Position(
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                current_price=entry_price,
            )
            db.add(position)

        trade = Trade(
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            fees=fees,
            status=TradeStatus.open.value,
            message=message,
        )
        db.add(trade)

        # Update strategy fees
        strategy = await db.get(Strategy, strategy_id)
        if strategy:
            strategy.current_equity -= fees
            strategy.total_trades += 1

        await db.commit()
        await db.refresh(position)
        await db.refresh(trade)

        await ws_manager.broadcast("position_update", {
            "action": "opened",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": entry_price,
            "strategy_id": strategy_id,
        })

        return position, trade

    async def close_position(
        self,
        db: AsyncSession,
        strategy_id: int,
        symbol: str,
        exit_price: float,
        fees: float,
        quantity: float | None = None,
        message: str = "",
    ) -> tuple[float, Trade | None]:
        """Close a position and calculate P&L. Returns (realized_pnl, trade)."""
        position = await self._get_position(db, strategy_id, symbol)
        if not position:
            return 0.0, None

        close_qty = quantity if quantity and quantity < position.quantity else position.quantity

        # Calculate P&L
        if position.side == "long":
            pnl = (exit_price - position.entry_price) * close_qty
        else:
            pnl = (position.entry_price - exit_price) * close_qty

        pnl -= fees
        pnl = round(pnl, 6)

        # Find the open trade to update
        stmt = (
            select(Trade)
            .where(
                Trade.strategy_id == strategy_id,
                Trade.symbol == symbol,
                Trade.status == TradeStatus.open.value,
            )
            .order_by(Trade.entry_time.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        trade = result.scalar_one_or_none()

        if trade:
            trade.exit_price = exit_price
            trade.exit_time = dt.datetime.utcnow()
            trade.realized_pnl = pnl
            trade.fees += fees
            trade.status = TradeStatus.closed.value

        # Update strategy
        strategy = await db.get(Strategy, strategy_id)
        if strategy:
            strategy.current_equity += pnl
            strategy.total_pnl += pnl
            if pnl > 0:
                strategy.winning_trades += 1
            if strategy.current_equity > strategy.peak_equity:
                strategy.peak_equity = strategy.current_equity

        # Handle partial vs full close
        if quantity and quantity < position.quantity:
            position.quantity -= quantity
            position.updated_at = dt.datetime.utcnow()
        else:
            await db.delete(position)

        await db.commit()

        await ws_manager.broadcast("trade_fill", {
            "action": "closed",
            "symbol": symbol,
            "side": position.side,
            "pnl": pnl,
            "exit_price": exit_price,
            "strategy_id": strategy_id,
        })

        return pnl, trade

    async def close_all_positions(
        self,
        db: AsyncSession,
        strategy_id: int,
    ) -> float:
        """Close all positions for a strategy. Returns total P&L."""
        stmt = select(Position).where(Position.strategy_id == strategy_id)
        result = await db.execute(stmt)
        positions = result.scalars().all()

        total_pnl = 0.0
        for pos in positions:
            price = await market_data.get_mid_price(pos.symbol)
            if price:
                from app.config import settings
                fees = price * pos.quantity * (settings.taker_fee_pct / 100)
                pnl, _ = await self.close_position(
                    db, strategy_id, pos.symbol, price, fees
                )
                total_pnl += pnl
        return total_pnl

    async def update_unrealized_pnl(self, db: AsyncSession):
        """Update unrealized P&L for all open positions."""
        stmt = select(Position)
        result = await db.execute(stmt)
        positions = result.scalars().all()

        updates = []
        for pos in positions:
            price = await market_data.get_mid_price(pos.symbol)
            if price:
                pos.current_price = price
                if pos.side == "long":
                    pos.unrealized_pnl = round((price - pos.entry_price) * pos.quantity, 6)
                else:
                    pos.unrealized_pnl = round((pos.entry_price - price) * pos.quantity, 6)
                pos.updated_at = dt.datetime.utcnow()
                updates.append({
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "current_price": price,
                    "strategy_id": pos.strategy_id,
                })

        await db.commit()
        if updates:
            await ws_manager.broadcast("pnl_update", updates)

    async def _get_position(
        self, db: AsyncSession, strategy_id: int, symbol: str
    ) -> Position | None:
        stmt = select(Position).where(
            Position.strategy_id == strategy_id,
            Position.symbol == symbol,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


position_manager = PositionManager()
