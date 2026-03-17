"""Position tracking & management endpoints for live trading.

ONE position per asset. Strategy manages all exits/flips regardless of origin.
"""

import asyncio
import datetime as dt
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import PositionTracking, LiveTrade, AssetConfig, AppSettings
from app.schemas import (
    PositionTrackingResponse,
    PositionOpenRequest,
    PositionAddRequest,
    PositionReduceRequest,
    PositionActionResponse,
    LiveTradeResponse,
    WebhookResponse,
)
from app.services.hl_account import hl_account
from app.services.market_data import market_data
from app.services.trading_engine import create_engine
from app.services.notification_service import notifier

logger = logging.getLogger(__name__)

router = APIRouter()


def _held_duration(opened_at: dt.datetime | None) -> str | None:
    if not opened_at:
        return None
    delta = dt.datetime.utcnow() - opened_at
    hours = int(delta.total_seconds() // 3600)
    mins = int((delta.total_seconds() % 3600) // 60)
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


async def _enrich_position(pt: PositionTracking) -> dict:
    """Add live data to a position tracking record."""
    data = {c.name: getattr(pt, c.name) for c in pt.__table__.columns}
    data["current_price"] = None
    data["unrealized_pnl"] = None
    data["pnl_pct"] = None
    data["leverage"] = None
    data["notional"] = None
    data["held_duration"] = _held_duration(pt.opened_at)

    if pt.direction and pt.total_size > 0 and pt.entry_price:
        price = await market_data.get_mid_price(pt.coin)
        if price:
            data["current_price"] = price
            # Get quantity from HL positions for accurate PnL
            try:
                hl_positions = await hl_account.get_open_positions()
                hl_pos = next((p for p in hl_positions if p["symbol"] == pt.coin), None)
                if hl_pos:
                    data["unrealized_pnl"] = hl_pos["unrealized_pnl"]
                    data["leverage"] = int(hl_pos["leverage"])
                    data["notional"] = hl_pos["notional"]
                    if hl_pos["entry_price"] > 0:
                        pnl_pct = ((price - hl_pos["entry_price"]) / hl_pos["entry_price"]) * 100
                        if pt.direction == "short":
                            pnl_pct = -pnl_pct
                        data["pnl_pct"] = round(pnl_pct, 2)
            except Exception:
                pass
    return data


async def _log_trade(
    db: AsyncSession,
    coin: str,
    action: str,
    origin: str,
    size: float,
    price: float,
    pnl: float | None,
    total_after: float,
    notes: str | None = None,
) -> LiveTrade:
    """Log a trade to the live_trades table."""
    trade = LiveTrade(
        coin=coin,
        action=action,
        origin=origin,
        size=size,
        price=price,
        pnl=pnl,
        total_position_after=total_after,
        notes=notes,
    )
    db.add(trade)
    return trade


async def _update_asset_stats(
    db: AsyncSession, coin: str, direction: str, price: float,
    pnl: float = 0.0, is_close: bool = False,
):
    """Update asset_configs stats after a trade."""
    result = await db.execute(select(AssetConfig).where(AssetConfig.coin == coin))
    asset = result.scalar_one_or_none()
    if asset is None:
        return
    asset.total_trades += 1
    if is_close and pnl > 0:
        asset.winning_trades += 1
    if is_close:
        asset.total_pnl += pnl
    asset.last_trade_at = dt.datetime.utcnow()
    asset.last_trade_direction = direction
    asset.last_trade_price = price
    asset.updated_at = dt.datetime.utcnow()


# ─── GET /api/positions (called via delegation from positions.py) ─────────────

async def list_positions(db: AsyncSession = Depends(get_db)):
    """Return all position tracking records enriched with live data."""
    result = await db.execute(select(PositionTracking).order_by(PositionTracking.coin))
    positions = result.scalars().all()
    enriched = []
    for pt in positions:
        data = await _enrich_position(pt)
        enriched.append(PositionTrackingResponse(**data))
    return enriched


# ─── POST /api/positions/{coin}/open ─────────────────────────────────────────────

@router.post("/positions/{coin}/open", response_model=PositionActionResponse)
async def open_position(coin: str, body: PositionOpenRequest, db: AsyncSession = Depends(get_db)):
    """Manually open a new position."""
    coin = coin.upper()

    # Check no existing position
    result = await db.execute(select(PositionTracking).where(PositionTracking.coin == coin))
    existing = result.scalar_one_or_none()
    if existing and existing.direction:
        raise HTTPException(400, f"{coin} already has a {existing.direction} position")

    # Get asset config for leverage
    asset_result = await db.execute(select(AssetConfig).where(AssetConfig.coin == coin))
    asset_cfg = asset_result.scalar_one_or_none()
    leverage = int(asset_cfg.leverage) if asset_cfg else int(round(settings.leverage))

    # Get price and calculate quantity
    price = await market_data.get_mid_price(coin)
    if not price:
        raise HTTPException(502, f"Cannot get price for {coin}")

    notional = body.amount_usd * leverage
    sz_decimals = await market_data.get_sz_decimals(coin)
    quantity = round(notional / price, sz_decimals)
    if quantity <= 0 or quantity * price < 10.0:
        raise HTTPException(400, f"Order too small: ${quantity * price:.2f}")

    # Execute
    action = "buy" if body.direction == "long" else "sell"
    engine = create_engine("live")
    result = await engine.execute_order_with_fallback(coin, action, quantity)
    if not result.success:
        raise HTTPException(502, f"Execution failed: {result.message}")

    fill_price = result.filled_price or price
    filled_notional = fill_price * (result.quantity or quantity)

    # Update or create tracking record
    now = dt.datetime.utcnow()
    if existing:
        existing.direction = body.direction
        existing.signal_size = 0.0
        existing.manual_size = filled_notional
        existing.total_size = filled_notional
        existing.entry_price = fill_price
        existing.opened_at = now
        existing.origin = "manual"
        existing.last_modified_at = now
        existing.last_modified_by = "manual_open"
        pt = existing
    else:
        pt = PositionTracking(
            coin=coin,
            direction=body.direction,
            signal_size=0.0,
            manual_size=filled_notional,
            total_size=filled_notional,
            entry_price=fill_price,
            opened_at=now,
            origin="manual",
            last_modified_at=now,
            last_modified_by="manual_open",
        )
        db.add(pt)

    await _log_trade(db, coin, f"open_{body.direction}", "manual_open",
                     filled_notional, fill_price, None, filled_notional,
                     f"Manual open {body.direction}")
    await db.commit()
    await db.refresh(pt)

    asyncio.create_task(notifier.notify_trade_open(
        symbol=coin, side=body.direction, quantity=result.quantity or quantity,
        price=fill_price, strategy_name="Manual", leverage=leverage,
    ))

    return PositionActionResponse(
        success=True,
        message=f"{coin} {body.direction.upper()} opened @ ${fill_price:,.2f} | ${filled_notional:,.2f} notional",
        position=PositionTrackingResponse(**(await _enrich_position(pt))),
    )


# ─── POST /api/positions/{coin}/add ──────────────────────────────────────────────

@router.post("/positions/{coin}/add", response_model=PositionActionResponse)
async def add_to_position(coin: str, body: PositionAddRequest, db: AsyncSession = Depends(get_db)):
    """Add to an existing position."""
    coin = coin.upper()

    result = await db.execute(select(PositionTracking).where(PositionTracking.coin == coin))
    pt = result.scalar_one_or_none()
    if not pt or not pt.direction:
        raise HTTPException(400, f"No open position for {coin}")

    # Calculate add amount
    add_notional = pt.total_size * (body.add_pct / 100)
    if add_notional < 10:
        raise HTTPException(400, f"Add amount too small: ${add_notional:.2f}")

    price = await market_data.get_mid_price(coin)
    if not price:
        raise HTTPException(502, f"Cannot get price for {coin}")

    sz_decimals = await market_data.get_sz_decimals(coin)
    quantity = round(add_notional / price, sz_decimals)
    if quantity <= 0:
        raise HTTPException(400, "Quantity rounds to zero")

    action = "buy" if pt.direction == "long" else "sell"
    engine = create_engine("live")
    result = await engine.execute_order_with_fallback(coin, action, quantity)
    if not result.success:
        raise HTTPException(502, f"Execution failed: {result.message}")

    fill_price = result.filled_price or price
    filled_notional = fill_price * (result.quantity or quantity)

    pt.manual_size += filled_notional
    pt.total_size = pt.signal_size + pt.manual_size
    pt.last_modified_at = dt.datetime.utcnow()
    pt.last_modified_by = "manual_add"

    await _log_trade(db, coin, f"add_{pt.direction}", "manual_add",
                     filled_notional, fill_price, None, pt.total_size,
                     f"User added {body.add_pct}%")
    await db.commit()
    await db.refresh(pt)

    asyncio.create_task(notifier._send_telegram(
        f"📈 Added ${filled_notional:,.2f} to {coin} {pt.direction.upper()}\n"
        f"Total: ${pt.total_size:,.2f} (signal: ${pt.signal_size:,.2f} + manual: ${pt.manual_size:,.2f})\n"
        f"Strategy manages exit."
    ))

    return PositionActionResponse(
        success=True,
        message=f"Added ${filled_notional:,.2f} to {coin} {pt.direction.upper()}. Total: ${pt.total_size:,.2f}",
        position=PositionTrackingResponse(**(await _enrich_position(pt))),
    )


# ─── POST /api/positions/{coin}/reduce ───────────────────────────────────────────

@router.post("/positions/{coin}/reduce", response_model=PositionActionResponse)
async def reduce_position(coin: str, body: PositionReduceRequest, db: AsyncSession = Depends(get_db)):
    """Partially close a position. Reduces signal_size and manual_size proportionally."""
    coin = coin.upper()

    result = await db.execute(select(PositionTracking).where(PositionTracking.coin == coin))
    pt = result.scalar_one_or_none()
    if not pt or not pt.direction:
        raise HTTPException(400, f"No open position for {coin}")

    # Get the HL position for actual quantity
    hl_positions = await hl_account.get_open_positions()
    hl_pos = next((p for p in hl_positions if p["symbol"] == coin), None)
    if not hl_pos:
        raise HTTPException(400, f"No Hyperliquid position for {coin}")

    reduce_qty = round(hl_pos["size"] * (body.reduce_pct / 100), await market_data.get_sz_decimals(coin))
    if reduce_qty <= 0:
        raise HTTPException(400, "Reduce quantity rounds to zero")

    reduce_notional = pt.total_size * (body.reduce_pct / 100)

    # Execute partial close
    close_action = "sell" if pt.direction == "long" else "buy"
    engine = create_engine("live")
    result = await engine.execute_order_with_fallback(coin, close_action, reduce_qty)
    if not result.success:
        raise HTTPException(502, f"Execution failed: {result.message}")

    fill_price = result.filled_price or hl_pos["mark_price"]

    # Calculate PnL on the reduced portion
    if pt.direction == "long":
        pnl = (fill_price - hl_pos["entry_price"]) * reduce_qty
    else:
        pnl = (hl_pos["entry_price"] - fill_price) * reduce_qty
    pnl = round(pnl, 4)

    # Reduce both proportionally
    ratio = body.reduce_pct / 100
    pt.signal_size *= (1 - ratio)
    pt.manual_size *= (1 - ratio)
    pt.total_size = pt.signal_size + pt.manual_size
    pt.last_modified_at = dt.datetime.utcnow()
    pt.last_modified_by = "manual_reduce"

    # If fully reduced, clear position
    if pt.total_size < 1.0:
        pt.direction = None
        pt.signal_size = 0.0
        pt.manual_size = 0.0
        pt.total_size = 0.0
        pt.entry_price = None
        pt.opened_at = None

    await _log_trade(db, coin, f"reduce_{hl_pos['side']}", "manual_reduce",
                     reduce_notional, fill_price, pnl, pt.total_size,
                     f"User reduced {body.reduce_pct}%")
    await _update_asset_stats(db, coin, "close", fill_price, pnl=pnl, is_close=True)
    await db.commit()
    await db.refresh(pt)

    held = _held_duration(pt.opened_at)
    pnl_sign = "+" if pnl >= 0 else ""
    asyncio.create_task(notifier._send_telegram(
        f"📉 Reduced {coin} {hl_pos['side'].upper()} by {body.reduce_pct}%\n"
        f"Closed ${reduce_notional:,.2f} | P&L: {pnl_sign}${pnl:,.2f}\n"
        f"Remaining: ${pt.total_size:,.2f}"
    ))

    return PositionActionResponse(
        success=True,
        message=f"Reduced {coin} by {body.reduce_pct}%. P&L: {pnl_sign}${pnl:,.2f}",
        pnl=pnl,
        held_duration=held,
        position=PositionTrackingResponse(**(await _enrich_position(pt))) if pt.direction else None,
    )


# ─── POST /api/positions/{coin}/close ────────────────────────────────────────────

@router.post("/positions/{coin}/close", response_model=PositionActionResponse)
async def close_position(coin: str, db: AsyncSession = Depends(get_db)):
    """Close an entire position."""
    coin = coin.upper()

    result = await db.execute(select(PositionTracking).where(PositionTracking.coin == coin))
    pt = result.scalar_one_or_none()

    # Also check HL directly
    hl_positions = await hl_account.get_open_positions()
    hl_pos = next((p for p in hl_positions if p["symbol"] == coin), None)
    if not hl_pos:
        if pt and pt.direction:
            # Tracking says open but HL says flat — clean up
            pt.direction = None
            pt.signal_size = 0.0
            pt.manual_size = 0.0
            pt.total_size = 0.0
            await db.commit()
        return PositionActionResponse(success=False, message=f"No open position for {coin}")

    # Close on HL
    close_action = "sell" if hl_pos["side"] == "long" else "buy"
    engine = create_engine("live")
    exec_result = await engine.execute_order_with_fallback(coin, close_action, hl_pos["size"])
    if not exec_result.success:
        raise HTTPException(502, f"Close failed: {exec_result.message}")

    fill_price = exec_result.filled_price or hl_pos["mark_price"]

    # PnL
    if hl_pos["side"] == "long":
        pnl = (fill_price - hl_pos["entry_price"]) * hl_pos["size"]
    else:
        pnl = (hl_pos["entry_price"] - fill_price) * hl_pos["size"]
    pnl = round(pnl, 4)

    closed_notional = pt.total_size if (pt and pt.total_size > 0) else hl_pos["notional"]
    opened_at = pt.opened_at if pt else None
    held = _held_duration(opened_at)

    # Update tracking
    if pt:
        await _log_trade(db, coin, f"close_{hl_pos['side']}", "manual_close",
                         closed_notional, fill_price, pnl, 0.0,
                         "User closed position")
        pt.direction = None
        pt.signal_size = 0.0
        pt.manual_size = 0.0
        pt.total_size = 0.0
        pt.entry_price = None
        pt.opened_at = None
        pt.last_modified_at = dt.datetime.utcnow()
        pt.last_modified_by = "manual_close"

    await _update_asset_stats(db, coin, "close", fill_price, pnl=pnl, is_close=True)
    await db.commit()

    pnl_sign = "+" if pnl >= 0 else ""
    leverage = int(hl_pos["leverage"])
    asyncio.create_task(notifier.notify_trade_close(
        symbol=coin, side=hl_pos["side"], quantity=hl_pos["size"],
        entry_price=hl_pos["entry_price"], exit_price=fill_price,
        pnl=pnl, strategy_name="Manual", leverage=leverage,
    ))

    return PositionActionResponse(
        success=True,
        message=f"{coin} {hl_pos['side'].upper()} closed @ ${fill_price:,.2f} | P&L: {pnl_sign}${pnl:,.2f}",
        pnl=pnl,
        held_duration=held,
    )


# ─── POST /api/positions/close-all ───────────────────────────────────────────────

@router.post("/positions/close-all", response_model=PositionActionResponse)
async def close_all_positions(db: AsyncSession = Depends(get_db)):
    """Close all positions and pause trading."""
    hl_positions = await hl_account.get_open_positions()
    if not hl_positions:
        return PositionActionResponse(success=False, message="No positions to close")

    engine = create_engine("live")
    results = []
    total_pnl = 0.0

    for pos in hl_positions:
        coin = pos["symbol"]
        close_action = "sell" if pos["side"] == "long" else "buy"
        exec_result = await engine.execute_order_with_fallback(coin, close_action, pos["size"])

        if exec_result.success:
            fill_price = exec_result.filled_price or pos["mark_price"]
            if pos["side"] == "long":
                pnl = (fill_price - pos["entry_price"]) * pos["size"]
            else:
                pnl = (pos["entry_price"] - fill_price) * pos["size"]
            pnl = round(pnl, 4)
            total_pnl += pnl

            # Update tracking
            pt_result = await db.execute(select(PositionTracking).where(PositionTracking.coin == coin))
            pt = pt_result.scalar_one_or_none()
            if pt:
                await _log_trade(db, coin, f"close_{pos['side']}", "manual_close",
                                 pt.total_size, fill_price, pnl, 0.0, "Kill switch")
                pt.direction = None
                pt.signal_size = 0.0
                pt.manual_size = 0.0
                pt.total_size = 0.0
                pt.entry_price = None
                pt.opened_at = None
                pt.last_modified_at = dt.datetime.utcnow()
                pt.last_modified_by = "manual_close"

            await _update_asset_stats(db, coin, "close", fill_price, pnl=pnl, is_close=True)
            pnl_sign = "+" if pnl >= 0 else ""
            results.append(f"{coin}: closed {pos['side'].upper()} P&L {pnl_sign}${pnl:,.2f}")
        else:
            results.append(f"{coin}: FAILED {exec_result.message}")

    # Pause trading
    settings_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    app_settings = settings_result.scalar_one_or_none()
    if app_settings:
        app_settings.trading_paused = True
        settings.trading_paused = True

    await db.commit()

    pnl_sign = "+" if total_pnl >= 0 else ""
    msg = "ALL POSITIONS CLOSED\n" + "\n".join(results) + f"\n\nTrading PAUSED. Total P&L: {pnl_sign}${total_pnl:,.2f}"

    asyncio.create_task(notifier._send_telegram(f"🔴 {msg}"))

    return PositionActionResponse(success=True, message=msg, pnl=total_pnl)


# ─── PATCH /api/positions/{coin}/leverage ────────────────────────────────────────

@router.patch("/positions/{coin}/leverage")
async def update_leverage(coin: str, leverage: int = Query(gt=0, le=100), db: AsyncSession = Depends(get_db)):
    """Update leverage for an asset, applying to HL if position is open."""
    coin = coin.upper()

    # Update DB
    asset_result = await db.execute(select(AssetConfig).where(AssetConfig.coin == coin))
    asset_cfg = asset_result.scalar_one_or_none()
    if not asset_cfg:
        raise HTTPException(404, f"Asset {coin} not found")

    old_leverage = asset_cfg.leverage
    asset_cfg.leverage = leverage
    asset_cfg.updated_at = dt.datetime.utcnow()
    await db.commit()

    # Check if there's an active HL position
    try:
        hl_positions = await hl_account.get_open_positions()
        hl_pos = next((p for p in hl_positions if p["symbol"] == coin), None)
    except Exception:
        hl_pos = None

    if hl_pos:
        # Apply leverage to HL
        try:
            engine = create_engine("live")
            exchange, _ = engine._get_clients()
            await asyncio.to_thread(exchange.update_leverage, leverage, coin, is_cross=True)
            return {
                "success": True,
                "message": f"{coin} leverage changed to {leverage}x. Active position updated.",
                "applied_to_position": True,
            }
        except Exception as e:
            logger.exception("Failed to update leverage on HL for %s", coin)
            return {
                "success": True,
                "message": f"{coin} leverage set to {leverage}x in DB but HL update failed: {e}",
                "applied_to_position": False,
            }
    else:
        return {
            "success": True,
            "message": f"{coin} leverage set to {leverage}x. Applied on next trade.",
            "applied_to_position": False,
        }


# ─── GET /api/trades (called via delegation from trades.py) ───────────────────

async def list_trades(
    limit: int = Query(default=20, ge=1, le=100),
    coin: str | None = None,
    origin: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Return trade log from live_trades table."""
    stmt = select(LiveTrade).order_by(desc(LiveTrade.timestamp))
    if coin:
        stmt = stmt.where(LiveTrade.coin == coin.upper())
    if origin:
        stmt = stmt.where(LiveTrade.origin == origin)
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
