import asyncio
import datetime as dt
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AssetConfig
from app.schemas import AssetConfigResponse, AssetConfigUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/assets", response_model=list[AssetConfigResponse])
async def list_assets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AssetConfig).order_by(AssetConfig.id))
    return result.scalars().all()


@router.get("/assets/{coin}", response_model=AssetConfigResponse)
async def get_asset(coin: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AssetConfig).where(AssetConfig.coin == coin.upper())
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Asset {coin} not found")
    return row


@router.patch("/assets/{coin}", response_model=AssetConfigResponse)
async def update_asset(
    coin: str, body: AssetConfigUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(AssetConfig).where(AssetConfig.coin == coin.upper())
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Asset {coin} not found")

    updates = body.model_dump(exclude_none=True)

    # If leverage is changing, apply to HL if there's an active position
    if "leverage" in updates:
        new_lev = updates["leverage"]
        old_lev = row.leverage
        if new_lev != old_lev:
            try:
                from app.services.hl_account import hl_account
                hl_positions = await hl_account.get_open_positions()
                hl_pos = next((p for p in hl_positions if p["symbol"] == coin.upper()), None)
                if hl_pos:
                    from app.services.trading_engine import create_engine
                    engine = create_engine("live")
                    exchange, _ = engine._get_clients()
                    await asyncio.to_thread(
                        exchange.update_leverage, new_lev, coin.upper(), is_cross=False
                    )
                    logger.info("Updated HL leverage for %s: %dx → %dx (position active)", coin.upper(), old_lev, new_lev)
            except Exception as e:
                logger.warning("Failed to update HL leverage for %s: %s", coin.upper(), e)

    for field, value in updates.items():
        setattr(row, field, value)
    row.updated_at = dt.datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return row
