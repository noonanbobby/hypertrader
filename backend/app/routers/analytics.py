import datetime as dt
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Trade, EquitySnapshot, Strategy, TradeStatus
from app.schemas import AnalyticsResponse, PnlDataPoint

router = APIRouter()


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    strategy_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # Equity curve from snapshots
    stmt = select(EquitySnapshot).order_by(EquitySnapshot.timestamp)
    if strategy_id:
        stmt = stmt.where(EquitySnapshot.strategy_id == strategy_id)
    result = await db.execute(stmt)
    snapshots = result.scalars().all()

    equity_curve = [
        PnlDataPoint(
            timestamp=s.timestamp, equity=s.equity, drawdown=s.drawdown
        )
        for s in snapshots
    ]

    # Closed trades
    trade_stmt = select(Trade).where(Trade.status == TradeStatus.closed.value)
    if strategy_id:
        trade_stmt = trade_stmt.where(Trade.strategy_id == strategy_id)
    trade_stmt = trade_stmt.order_by(Trade.exit_time)
    result = await db.execute(trade_stmt)
    closed_trades = list(result.scalars().all())

    total = len(closed_trades)
    wins = [t for t in closed_trades if t.realized_pnl > 0]
    losses = [t for t in closed_trades if t.realized_pnl <= 0]

    win_rate = (len(wins) / total * 100) if total > 0 else 0.0
    avg_win = sum(t.realized_pnl for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.realized_pnl for t in losses) / len(losses) if losses else 0.0

    gross_profit = sum(t.realized_pnl for t in wins) if wins else 0.0
    gross_loss = abs(sum(t.realized_pnl for t in losses)) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    # Max drawdown from snapshots
    max_dd = 0.0
    if snapshots:
        max_dd = max(s.drawdown for s in snapshots)

    # Sharpe ratio (simplified - daily returns std)
    sharpe = 0.0
    if len(closed_trades) > 1:
        returns = [t.realized_pnl for t in closed_trades]
        avg_ret = sum(returns) / len(returns)
        variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
        std = variance ** 0.5
        if std > 0:
            sharpe = round((avg_ret / std) * (252 ** 0.5), 2)

    # Monthly returns
    monthly_returns: dict[str, float] = {}
    for t in closed_trades:
        if t.exit_time:
            key = t.exit_time.strftime("%Y-%m")
            monthly_returns[key] = monthly_returns.get(key, 0.0) + t.realized_pnl

    # Average trade duration
    avg_duration = 0.0
    durations = []
    for t in closed_trades:
        if t.exit_time and t.entry_time:
            delta = (t.exit_time - t.entry_time).total_seconds() / 3600
            durations.append(delta)
    if durations:
        avg_duration = sum(durations) / len(durations)

    return AnalyticsResponse(
        equity_curve=equity_curve,
        monthly_returns={k: round(v, 2) for k, v in monthly_returns.items()},
        win_rate=round(win_rate, 1),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        max_drawdown=round(max_dd, 2),
        sharpe_ratio=sharpe,
        total_trades=total,
        avg_trade_duration_hours=round(avg_duration, 1),
    )
