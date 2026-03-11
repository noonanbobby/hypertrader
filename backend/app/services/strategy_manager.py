from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Strategy, StrategyStatus


class StrategyManager:
    async def get_strategy_by_name(
        self, db: AsyncSession, name: str
    ) -> Strategy | None:
        stmt = select(Strategy).where(Strategy.name == name)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_strategies(self, db: AsyncSession) -> list[Strategy]:
        stmt = select(Strategy).where(Strategy.status == StrategyStatus.active.value)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_strategy(
        self,
        db: AsyncSession,
        name: str,
        description: str = "",
        allocated_capital: float = 10000.0,
        max_position_pct: float = 25.0,
        max_drawdown_pct: float = 10.0,
    ) -> Strategy:
        strategy = Strategy(
            name=name,
            description=description,
            allocated_capital=allocated_capital,
            current_equity=allocated_capital,
            peak_equity=allocated_capital,
            max_position_pct=max_position_pct,
            max_drawdown_pct=max_drawdown_pct,
        )
        db.add(strategy)
        await db.commit()
        await db.refresh(strategy)
        return strategy

    async def get_or_create_strategy(
        self, db: AsyncSession, name: str
    ) -> Strategy:
        """Get existing strategy or auto-create one."""
        strategy = await self.get_strategy_by_name(db, name)
        if not strategy:
            strategy = await self.create_strategy(db, name)
        return strategy

    async def update_strategy(
        self, db: AsyncSession, strategy_id: int, **kwargs
    ) -> Strategy | None:
        strategy = await db.get(Strategy, strategy_id)
        if not strategy:
            return None

        # If allocated_capital changes, adjust current_equity and peak_equity
        new_capital = kwargs.get("allocated_capital")
        if new_capital is not None and new_capital != strategy.allocated_capital:
            old_capital = strategy.allocated_capital
            delta = new_capital - old_capital
            strategy.allocated_capital = new_capital
            strategy.current_equity += delta
            strategy.peak_equity = max(strategy.peak_equity + delta, strategy.current_equity)
            kwargs.pop("allocated_capital")

        for key, value in kwargs.items():
            if value is not None and hasattr(strategy, key):
                setattr(strategy, key, value)
        await db.commit()
        await db.refresh(strategy)
        return strategy

    async def delete_strategy(self, db: AsyncSession, strategy_id: int) -> bool:
        strategy = await db.get(Strategy, strategy_id)
        if not strategy:
            return False
        await db.delete(strategy)
        await db.commit()
        return True


strategy_manager = StrategyManager()
