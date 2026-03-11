from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Position, Strategy
from app.schemas import PositionResponse
from app.services.position_manager import position_manager

router = APIRouter()


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions(
    strategy_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # Update unrealized P&L before returning
    await position_manager.update_unrealized_pnl(db)

    stmt = select(Position).order_by(Position.opened_at.desc())
    if strategy_id:
        stmt = stmt.where(Position.strategy_id == strategy_id)

    result = await db.execute(stmt)
    positions = result.scalars().all()

    strategy_ids = {p.strategy_id for p in positions}
    strategies = {}
    for sid in strategy_ids:
        s = await db.get(Strategy, sid)
        if s:
            strategies[sid] = s.name

    leverage = settings.leverage

    return [
        PositionResponse(
            id=p.id,
            strategy_id=p.strategy_id,
            strategy_name=strategies.get(p.strategy_id, ""),
            symbol=p.symbol,
            side=p.side,
            entry_price=p.entry_price,
            quantity=p.quantity,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
            pnl_pct=round(
                (p.unrealized_pnl / (p.entry_price * p.quantity / leverage) * 100)
                if p.entry_price * p.quantity > 0
                else 0.0,
                2,
            ),
            notional_value=round(p.current_price * p.quantity, 2),
            margin_used=round(p.entry_price * p.quantity / leverage, 2),
            leverage=leverage,
            opened_at=p.opened_at,
        )
        for p in positions
    ]
