import datetime as dt
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Trade, Strategy
from app.schemas import TradeResponse

router = APIRouter()


@router.get("/trades", response_model=list[TradeResponse])
async def list_trades(
    strategy_id: Optional[int] = Query(None),
    symbol: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Trade).join(Strategy).order_by(desc(Trade.entry_time))

    if strategy_id:
        stmt = stmt.where(Trade.strategy_id == strategy_id)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol.upper())
    if side:
        stmt = stmt.where(Trade.side == side)
    if status:
        stmt = stmt.where(Trade.status == status)
    if start_date:
        stmt = stmt.where(Trade.entry_time >= dt.datetime.fromisoformat(start_date))
    if end_date:
        stmt = stmt.where(Trade.entry_time <= dt.datetime.fromisoformat(end_date))

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    trades = result.scalars().all()

    # Fetch strategy names
    strategy_ids = {t.strategy_id for t in trades}
    strategies = {}
    for sid in strategy_ids:
        s = await db.get(Strategy, sid)
        if s:
            strategies[sid] = s.name

    leverage = settings.leverage

    return [
        TradeResponse(
            id=t.id,
            strategy_id=t.strategy_id,
            strategy_name=strategies.get(t.strategy_id, ""),
            symbol=t.symbol,
            side=t.side,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            quantity=t.quantity,
            notional_value=round(t.entry_price * t.quantity, 2),
            margin_used=round(t.entry_price * t.quantity / leverage, 2),
            leverage=leverage,
            realized_pnl=t.realized_pnl,
            fees=t.fees,
            status=t.status,
            entry_time=t.entry_time,
            exit_time=t.exit_time,
            message=t.message,
        )
        for t in trades
    ]
