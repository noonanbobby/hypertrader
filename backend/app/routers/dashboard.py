import datetime as dt
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Strategy, Trade, Position, TradeStatus
from app.schemas import DashboardStats
from app.services.position_manager import position_manager

router = APIRouter()


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    # Update unrealized P&L with live prices before computing stats
    await position_manager.update_unrealized_pnl(db)

    # Total equity across all strategies (realized only)
    stmt = select(func.coalesce(func.sum(Strategy.current_equity), 0.0))
    result = await db.execute(stmt)
    total_equity = float(result.scalar())

    # Total realized P&L
    stmt = select(func.coalesce(func.sum(Strategy.total_pnl), 0.0))
    result = await db.execute(stmt)
    total_pnl = float(result.scalar())

    # Add unrealized P&L from open positions
    stmt = select(func.coalesce(func.sum(Position.unrealized_pnl), 0.0))
    result = await db.execute(stmt)
    total_unrealized = float(result.scalar())

    total_equity += total_unrealized
    total_pnl += total_unrealized

    # Period P&L calculations (realized)
    now = dt.datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - dt.timedelta(days=7)
    month_ago = today - dt.timedelta(days=30)

    daily_pnl = await _period_pnl(db, today) + total_unrealized
    weekly_pnl = await _period_pnl(db, week_ago) + total_unrealized
    monthly_pnl = await _period_pnl(db, month_ago) + total_unrealized

    # Open positions count
    stmt = select(func.count(Position.id))
    result = await db.execute(stmt)
    open_positions = int(result.scalar())

    # Active strategies count
    stmt = select(func.count(Strategy.id)).where(Strategy.status == "active")
    result = await db.execute(stmt)
    active_strategies = int(result.scalar())

    # Trade stats
    stmt = select(func.count(Trade.id))
    result = await db.execute(stmt)
    total_trades = int(result.scalar())

    stmt = select(func.count(Trade.id)).where(
        Trade.status == TradeStatus.closed.value, Trade.realized_pnl > 0
    )
    result = await db.execute(stmt)
    winning = int(result.scalar())

    closed_stmt = select(func.count(Trade.id)).where(
        Trade.status == TradeStatus.closed.value
    )
    result = await db.execute(closed_stmt)
    total_closed = int(result.scalar())

    win_rate = (winning / total_closed * 100) if total_closed > 0 else 0.0

    # Best/worst trade
    stmt = select(func.max(Trade.realized_pnl)).where(
        Trade.status == TradeStatus.closed.value
    )
    result = await db.execute(stmt)
    best_trade = float(result.scalar() or 0.0)

    stmt = select(func.min(Trade.realized_pnl)).where(
        Trade.status == TradeStatus.closed.value
    )
    result = await db.execute(stmt)
    worst_trade = float(result.scalar() or 0.0)

    return DashboardStats(
        total_equity=round(total_equity, 2),
        total_pnl=round(total_pnl, 2),
        daily_pnl=round(daily_pnl, 2),
        weekly_pnl=round(weekly_pnl, 2),
        monthly_pnl=round(monthly_pnl, 2),
        open_positions=open_positions,
        active_strategies=active_strategies,
        total_trades=total_trades,
        win_rate=round(win_rate, 1),
        best_trade=round(best_trade, 2),
        worst_trade=round(worst_trade, 2),
        trading_mode=settings.trading_mode,
    )


async def _period_pnl(db: AsyncSession, since: dt.datetime) -> float:
    stmt = select(func.coalesce(func.sum(Trade.realized_pnl), 0.0)).where(
        Trade.status == TradeStatus.closed.value,
        Trade.exit_time >= since,
    )
    result = await db.execute(stmt)
    return float(result.scalar())
