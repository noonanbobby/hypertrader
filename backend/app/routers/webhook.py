import asyncio
import json
import datetime as dt
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, async_session
from app.schemas import WebhookPayload, WebhookResponse
from app.models import WebhookLog, Position
from app.services.trading_engine import create_engine
from app.services.market_data import market_data
from app.services.strategy_manager import strategy_manager
from app.services.position_manager import position_manager
from app.services.risk_manager import risk_manager
from app.services.notification_service import notifier

router = APIRouter()

# Per-(strategy, symbol) locks to prevent race conditions when
# concurrent webhooks arrive for the same position (e.g. two signals 1s apart).
_webhook_locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)


@router.post("/webhook", response_model=WebhookResponse)
async def receive_webhook(payload: WebhookPayload, db: AsyncSession = Depends(get_db)):
    # Log the webhook
    log = WebhookLog(
        raw_payload=json.dumps(payload.model_dump(), default=str),
        parsed_action=payload.action,
        strategy_name=payload.strategy,
        symbol=payload.symbol,
    )

    # Validate secret
    if payload.secret != settings.webhook_secret:
        log.result = "Invalid secret"
        log.success = 0
        db.add(log)
        await db.commit()
        return WebhookResponse(success=False, message="Invalid webhook secret")

    # Get trading engine
    engine = create_engine(settings.trading_mode)

    action = payload.action.lower()
    symbol = payload.symbol.upper()

    # Acquire per-(strategy, symbol) lock to prevent race conditions
    # when concurrent webhooks arrive for the same position.
    lock = _webhook_locks[(payload.strategy, symbol)]
    async with lock:
        # Use a fresh session inside the lock to guarantee we see the
        # latest committed state (no stale objects from before the lock).
        async with async_session() as sdb:
            try:
                result = await _process_webhook(
                    sdb, engine, payload, action, symbol, log
                )
                return result
            except Exception as e:
                log.result = str(e)
                log.success = 0
                sdb.add(log)
                await sdb.commit()
                return WebhookResponse(success=False, message=str(e))


async def _process_webhook(
    db: AsyncSession,
    engine,
    payload: WebhookPayload,
    action: str,
    symbol: str,
    log: WebhookLog,
) -> WebhookResponse:
    """Process webhook inside the lock with a fresh DB session."""
    strategy = await strategy_manager.get_or_create_strategy(db, payload.strategy)

    if action in ("buy", "sell"):
        new_side = "long" if action == "buy" else "short"

        # Get current price
        price = await engine.get_current_price(symbol)
        if not price:
            raise ValueError(f"Cannot get price for {symbol}")

        # Resolve szDecimals for quantity rounding
        coin = market_data.normalize_coin(symbol)
        sz_decimals = await market_data.get_sz_decimals(coin)

        # Use integer leverage for Hyperliquid compatibility
        leverage = int(round(settings.leverage))

        # --- Check for existing position (flip detection) ---
        existing = await _get_existing_position(db, strategy.id, symbol)

        # Same-side signal = duplicate (e.g. TradingView fires twice) → no-op
        if existing is not None and existing.side == new_side:
            msg = f"Already {existing.side} {symbol} — duplicate signal ignored"
            log.result = msg
            log.success = 1
            db.add(log)
            await db.commit()
            return WebhookResponse(success=True, message=msg)

        # --- Opposite-side signal = close existing position only ---
        # TradingView sends close + open as two separate signals.
        # First signal closes; the follow-up signal opens the new direction.
        if existing is not None:
            close_action = "sell" if existing.side == "long" else "buy"
            close_result = await engine.execute_order_with_fallback(
                symbol, close_action, existing.quantity,
            )
            if not close_result.success:
                raise ValueError(f"Close failed: {close_result.message}")

            pnl, _ = await position_manager.close_position(
                db=db,
                strategy_id=strategy.id,
                symbol=symbol,
                exit_price=close_result.filled_price,
                fees=close_result.fees,
                message=f"Closed for {action} signal",
            )
            asyncio.create_task(notifier.notify_trade_close(
                symbol=symbol, side=existing.side,
                quantity=existing.quantity, entry_price=existing.entry_price,
                exit_price=close_result.filled_price, pnl=pnl,
                strategy_name=payload.strategy, leverage=leverage,
            ))

            msg = f"Closed {existing.side} {symbol} P&L: ${pnl:.2f}"
            log.result = msg
            log.success = 1
            db.add(log)
            await db.commit()
            return WebhookResponse(success=True, message=msg)

        # --- NEW POSITION (no existing position) ---
        # Calculate quantity
        size_pct = payload.size_pct or settings.default_size_pct
        quantity = payload.quantity or 0.0
        if quantity <= 0:
            margin = strategy.current_equity * (size_pct / 100)
            notional = margin * leverage
            quantity = notional / price

        # Round to szDecimals
        quantity = round(quantity, sz_decimals)
        if quantity <= 0:
            raise ValueError("Calculated quantity is zero after rounding to szDecimals")

        # Minimum $10 notional check (Hyperliquid rejects below this)
        if quantity * price < 10.0:
            raise ValueError(
                f"Order notional ${quantity * price:.2f} below Hyperliquid minimum of $10"
            )

        # Risk check before executing
        allowed, reason = await risk_manager.check_trade(
            db, strategy, symbol, quantity, price
        )
        if not allowed:
            asyncio.create_task(notifier.notify_risk_breach(
                strategy_name=payload.strategy, symbol=symbol, reason=reason,
            ))
            raise ValueError(f"Risk check failed: {reason}")

        # Execute new position
        result = await engine.execute_order_with_fallback(symbol, action, quantity)
        if not result.success:
            raise ValueError(result.message)

        # Record new position
        pos, trade = await position_manager.open_position(
            db=db,
            strategy_id=strategy.id,
            symbol=symbol,
            side=new_side,
            entry_price=result.filled_price,
            quantity=result.quantity,
            fees=result.fees,
            message=payload.message,
            fill_type=result.fill_type,
        )

        # Fire-and-forget Telegram notification
        asyncio.create_task(notifier.notify_trade_open(
            symbol=symbol, side=new_side, quantity=result.quantity,
            price=result.filled_price, strategy_name=payload.strategy,
            fill_type=result.fill_type, leverage=leverage,
        ))

        msg = result.message
        log.result = msg
        log.success = 1
        db.add(log)
        await db.commit()
        return WebhookResponse(
            success=True, message=msg, trade_id=trade.id
        )

    elif action in ("close_long", "close_short", "close_all"):
        if action == "close_all":
            total_pnl = await position_manager.close_all_positions(db, strategy.id)
            log.result = f"Closed all. P&L: {total_pnl:.4f}"
            log.success = 1
            db.add(log)
            await db.commit()
            return WebhookResponse(
                success=True, message=f"Closed all. P&L: ${total_pnl:.2f}"
            )

        # Close specific side
        existing = await _get_existing_position(db, strategy.id, symbol)
        if not existing:
            log.result = "No position to close"
            log.success = 0
            db.add(log)
            await db.commit()
            return WebhookResponse(success=False, message="No position to close")

        result = await engine.execute_order_with_fallback(
            symbol,
            "sell" if existing.side == "long" else "buy",
            existing.quantity,
        )
        if not result.success:
            raise ValueError(result.message)

        pnl, trade = await position_manager.close_position(
            db=db,
            strategy_id=strategy.id,
            symbol=symbol,
            exit_price=result.filled_price,
            fees=result.fees,
            message=payload.message,
        )

        asyncio.create_task(notifier.notify_trade_close(
            symbol=symbol, side=existing.side,
            quantity=existing.quantity, entry_price=existing.entry_price,
            exit_price=result.filled_price, pnl=pnl,
            strategy_name=payload.strategy, leverage=settings.leverage,
        ))

        log.result = f"Closed position. P&L: {pnl:.4f}"
        log.success = 1
        db.add(log)
        await db.commit()
        return WebhookResponse(
            success=True,
            message=f"Position closed. P&L: ${pnl:.2f}",
            trade_id=trade.id if trade else None,
        )

    else:
        raise ValueError(f"Unknown action: {action}")


async def _get_existing_position(
    db: AsyncSession, strategy_id: int, symbol: str
) -> Position | None:
    stmt = select(Position).where(
        Position.strategy_id == strategy_id,
        Position.symbol == symbol,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
