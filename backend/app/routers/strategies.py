from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Strategy
from app.schemas import StrategyCreate, StrategyUpdate, StrategyResponse
from app.services.strategy_manager import strategy_manager

router = APIRouter()


def _to_response(s: Strategy) -> StrategyResponse:
    win_rate = (s.winning_trades / s.total_trades * 100) if s.total_trades > 0 else 0.0
    current_dd = 0.0
    if s.peak_equity > 0:
        current_dd = (s.peak_equity - s.current_equity) / s.peak_equity * 100
    return StrategyResponse(
        id=s.id,
        name=s.name,
        description=s.description,
        allocated_capital=s.allocated_capital,
        current_equity=s.current_equity,
        max_position_pct=s.max_position_pct,
        max_drawdown_pct=s.max_drawdown_pct,
        status=s.status,
        total_trades=s.total_trades,
        winning_trades=s.winning_trades,
        total_pnl=s.total_pnl,
        peak_equity=s.peak_equity,
        win_rate=round(win_rate, 1),
        current_drawdown=round(max(current_dd, 0), 2),
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.get("/strategies", response_model=list[StrategyResponse])
async def list_strategies(db: AsyncSession = Depends(get_db)):
    stmt = select(Strategy).order_by(Strategy.created_at.desc())
    result = await db.execute(stmt)
    strategies = result.scalars().all()
    return [_to_response(s) for s in strategies]


@router.get("/strategies/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _to_response(strategy)


@router.post("/strategies", response_model=StrategyResponse, status_code=201)
async def create_strategy(data: StrategyCreate, db: AsyncSession = Depends(get_db)):
    existing = await strategy_manager.get_strategy_by_name(db, data.name)
    if existing:
        raise HTTPException(status_code=409, detail="Strategy name already exists")
    strategy = await strategy_manager.create_strategy(
        db,
        name=data.name,
        description=data.description,
        allocated_capital=data.allocated_capital,
        max_position_pct=data.max_position_pct,
        max_drawdown_pct=data.max_drawdown_pct,
    )
    return _to_response(strategy)


@router.patch("/strategies/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int, data: StrategyUpdate, db: AsyncSession = Depends(get_db)
):
    strategy = await strategy_manager.update_strategy(
        db, strategy_id, **data.model_dump(exclude_unset=True)
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _to_response(strategy)


@router.delete("/strategies/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    deleted = await strategy_manager.delete_strategy(db, strategy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Strategy not found")
