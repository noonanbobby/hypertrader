import datetime as dt
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Strategy, Trade, Position, TradeStatus


class RiskManager:
    async def check_trade(
        self,
        db: AsyncSession,
        strategy: Strategy,
        symbol: str,
        quantity: float,
        price: float,
    ) -> tuple[bool, str]:
        """Run pre-trade risk checks. Returns (allowed, reason)."""
        # 1. Check strategy is active
        if strategy.status != "active":
            return False, f"Strategy '{strategy.name}' is paused"

        # 2. Check position size limit
        notional = quantity * price
        max_notional = strategy.current_equity * (strategy.max_position_pct / 100)
        # 0.5% tolerance to avoid rejection from price/quantity rounding
        if notional > max_notional * 1.005:
            return False, (
                f"Position size ${notional:.2f} exceeds "
                f"{strategy.max_position_pct}% limit (${max_notional:.2f})"
            )

        # 3. Check drawdown limit
        if strategy.peak_equity > 0:
            current_dd = (
                (strategy.peak_equity - strategy.current_equity)
                / strategy.peak_equity
                * 100
            )
            if current_dd >= strategy.max_drawdown_pct:
                return False, (
                    f"Drawdown {current_dd:.1f}% exceeds "
                    f"limit {strategy.max_drawdown_pct}%"
                )

        # 4. Check daily loss limit
        daily_pnl = await self._get_daily_pnl(db, strategy.id)
        from app.config import settings
        if daily_pnl <= -settings.default_daily_loss_limit:
            return False, (
                f"Daily loss ${abs(daily_pnl):.2f} exceeds "
                f"limit ${settings.default_daily_loss_limit:.2f}"
            )

        return True, "OK"

    async def check_trade_live(
        self,
        db: AsyncSession,
        symbol: str,
        quantity: float,
        price: float,
        account_balance: float,
    ) -> tuple[bool, str]:
        """Run pre-trade risk checks for live mode (no strategy). Returns (allowed, reason)."""
        from app.config import settings

        # 1. Position size check: margin vs account_balance * default_max_position_pct
        notional = quantity * price
        leverage = settings.leverage if settings.leverage > 0 else 1
        margin = notional / leverage
        max_margin = account_balance * (settings.default_max_position_pct / 100)
        if margin > max_margin * 1.005:
            return False, (
                f"Margin ${margin:.2f} exceeds "
                f"{settings.default_max_position_pct}% limit (${max_margin:.2f})"
            )

        # 2. Daily loss limit check against webhook_logs for today
        daily_pnl = await self._get_daily_pnl_live(db)
        if daily_pnl <= -settings.default_daily_loss_limit:
            return False, (
                f"Daily loss ${abs(daily_pnl):.2f} exceeds "
                f"limit ${settings.default_daily_loss_limit:.2f}"
            )

        return True, "OK"

    async def _get_daily_pnl(self, db: AsyncSession, strategy_id: int) -> float:
        today = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(func.coalesce(func.sum(Trade.realized_pnl), 0.0)).where(
            Trade.strategy_id == strategy_id,
            Trade.status == TradeStatus.closed.value,
            Trade.exit_time >= today,
        )
        result = await db.execute(stmt)
        return float(result.scalar())

    async def _get_daily_pnl_live(self, db: AsyncSession) -> float:
        """Get today's realized PNL from webhook_logs for live mode."""
        today = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        # For live mode, we check trades table for strategy_name='__live__'
        stmt = select(func.coalesce(func.sum(Trade.realized_pnl), 0.0)).where(
            Trade.strategy_id == 0,
            Trade.status == TradeStatus.closed.value,
            Trade.exit_time >= today,
        )
        result = await db.execute(stmt)
        return float(result.scalar())


risk_manager = RiskManager()
