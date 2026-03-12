import asyncio
import json
import datetime as dt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas import WebhookPayload, WebhookResponse
from app.models import WebhookLog, Position
from app.services.trading_engine import create_engine
from app.services.strategy_manager import strategy_manager
from app.services.position_manager import position_manager
from app.services.risk_manager import risk_manager
from app.services.notification_service import notifier

router = APIRouter()


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

    # Get or create strategy (acts as the wallet)
    strategy = await strategy_manager.get_or_create_strategy(db, payload.strategy)

    # Get trading engine
    engine = create_engine(settings.trading_mode)

    action = payload.action.lower()
    symbol = payload.symbol.upper()

    try:
        if action in ("buy", "sell"):
            new_side = "long" if action == "buy" else "short"

            # Get current price
            price = await engine.get_current_price(symbol)
            if not price:
                raise ValueError(f"Cannot get price for {symbol}")

            # --- FLIP LOGIC: close any existing position first ---
            close_msg = ""
            existing = await _get_existing_position(db, strategy.id, symbol)
            if existing:
                # Close the existing position regardless of side
                close_result = await engine.execute_order_with_fallback(
                    symbol,
                    "sell" if existing.side == "long" else "buy",
                    existing.quantity,
                )
                if close_result.success:
                    pnl, _ = await position_manager.close_position(
                        db=db,
                        strategy_id=strategy.id,
                        symbol=symbol,
                        exit_price=close_result.filled_price,
                        fees=close_result.fees,
                        message=f"Auto-closed for {action} signal",
                    )
                    asyncio.create_task(notifier.notify_trade_close(
                        symbol=symbol, side=existing.side,
                        quantity=existing.quantity, entry_price=existing.entry_price,
                        exit_price=close_result.filled_price, pnl=pnl,
                        strategy_name=payload.strategy, leverage=settings.leverage,
                    ))
                    close_msg = f"Closed {existing.side} P&L: ${pnl:.2f} | "
                    # Refresh strategy to get updated equity
                    await db.refresh(strategy)

            # --- Open new position with size_pct of current equity (leveraged) ---
            size_pct = payload.size_pct or 10.0  # default 10%
            leverage = settings.leverage  # default 10x
            quantity = payload.quantity or 0.0
            if quantity <= 0:
                margin = strategy.current_equity * (size_pct / 100)
                notional = margin * leverage  # 10x leverage
                quantity = round(notional / price, 6)
            if quantity <= 0:
                raise ValueError("Calculated quantity is zero")

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

            msg = f"{close_msg}{result.message}"
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

    except Exception as e:
        log.result = str(e)
        log.success = 0
        db.add(log)
        await db.commit()
        return WebhookResponse(success=False, message=str(e))


async def _get_existing_position(
    db: AsyncSession, strategy_id: int, symbol: str
) -> Position | None:
    stmt = select(Position).where(
        Position.strategy_id == strategy_id,
        Position.symbol == symbol,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
