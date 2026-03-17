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

    # If leverage is changing, apply to HL immediately via leverage manager
    if "leverage" in updates:
        new_lev = updates["leverage"]
        old_lev = row.leverage
        if new_lev != old_lev:
            try:
                from app.services.leverage_manager import _get_exchange, _set_leverage
                exchange = await _get_exchange()
                if exchange:
                    ok, msg = await _set_leverage(exchange, coin.upper(), new_lev)
                    if ok:
                        logger.info("Leverage updated: %s %dx → %dx isolated", coin.upper(), old_lev, new_lev)
                    else:
                        logger.warning("Leverage update failed for %s: %s", coin.upper(), msg)
            except Exception as e:
                logger.warning("Failed to update HL leverage for %s: %s", coin.upper(), e)

    for field, value in updates.items():
        setattr(row, field, value)
    row.updated_at = dt.datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return row
