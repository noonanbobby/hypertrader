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
from app.models import WebhookLog, Position, AssetConfig, PositionTracking, LiveTrade
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
        strategy_name=payload.strategy or "__live__",
        symbol=payload.symbol,
    )

    # Validate secret
    if payload.secret != settings.webhook_secret:
        log.result = "Invalid secret"
        log.success = 0
        db.add(log)
        await db.commit()
        return WebhookResponse(success=False, message="Invalid webhook secret")

    # Check if trading is paused
    if settings.trading_paused:
        log.result = "Trading paused — signal ignored"
        log.success = 0
        db.add(log)
        await db.commit()
        return WebhookResponse(success=False, message="Trading is paused")

    # Get trading engine — live mode always uses live engine
    if settings.trading_mode == "live":
        engine = create_engine("live")
    else:
        engine = create_engine(settings.trading_mode)

    action = payload.action.lower()
    # Normalize TradingView symbols (BTCUSDT.P → BTC)
    symbol = market_data.normalize_coin(payload.symbol)

    # Route to live or paper processing
    if settings.trading_mode == "live":
        lock_key = ("__live__", symbol)
        lock = _webhook_locks[lock_key]
        async with lock:
            async with async_session() as sdb:
                try:
                    result = await _process_webhook_live(
                        sdb, engine, payload, action, symbol, log
                    )
                    return result
                except Exception as e:
                    log.result = str(e)
                    log.success = 0
                    sdb.add(log)
                    await sdb.commit()
                    return WebhookResponse(success=False, message=str(e))
    else:
        # Paper mode — strategy is required
        if not payload.strategy:
            log.result = "Strategy name required for paper trading"
            log.success = 0
            db.add(log)
            await db.commit()
            return WebhookResponse(
                success=False, message="Strategy name required for paper trading"
            )

        lock = _webhook_locks[(payload.strategy, symbol)]
        async with lock:
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

        # --- Opposite-side signal = close existing, then open new ---
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

            # Refresh strategy equity after close (P&L applied)
            await db.refresh(strategy)

        # --- OPEN NEW POSITION ---
        # Calculate quantity
        size_pct = payload.size_pct or settings.default_size_pct
        quantity = payload.quantity or 0.0
        if quantity <= 0:
            if settings.use_max_size and not payload.size_pct:
                # Max size mode: size up to strategy's max_position_pct
                notional = strategy.current_equity * (strategy.max_position_pct / 100)
            else:
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
        if existing is not None:
            msg = f"Flipped {existing.side}→{new_side} {symbol} (P&L: ${pnl:.2f}) | {msg}"
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


async def _process_webhook_live(
    db: AsyncSession,
    engine,
    payload: WebhookPayload,
    action: str,
    symbol: str,
    log: WebhookLog,
) -> WebhookResponse:
    """Process webhook in live mode with position tracking integration."""
    coin = symbol

    # Look up per-asset config from DB
    asset_result = await db.execute(
        select(AssetConfig).where(AssetConfig.coin == coin)
    )
    asset_cfg = asset_result.scalar_one_or_none()

    leverage = int(asset_cfg.leverage) if asset_cfg else int(round(settings.leverage))
    fixed_amount = asset_cfg.fixed_trade_amount_usd if asset_cfg else None

    if asset_cfg and not asset_cfg.enabled:
        log.result = f"Asset {coin} is disabled"
        log.success = 0
        db.add(log)
        await db.commit()
        return WebhookResponse(success=False, message=f"Asset {coin} is disabled")

    # Look up position tracking
    pt_result = await db.execute(
        select(PositionTracking).where(PositionTracking.coin == coin)
    )
    pt = pt_result.scalar_one_or_none()

    # Determine origin from payload
    origin = "signal"
    if payload.message and "reconciler" in payload.message.lower():
        origin = "reconciler"

    if action in ("buy", "sell"):
        new_side = "long" if action == "buy" else "short"

        price = await engine.get_current_price(coin)
        if not price:
            raise ValueError(f"Cannot get price for {coin}")

        sz_decimals = await market_data.get_sz_decimals(coin)

        # Check existing HL position
        from app.services.hl_account import hl_account
        hl_positions = await hl_account.get_open_positions()
        existing = next((p for p in hl_positions if p["symbol"] == coin), None)

        # Same-side = duplicate → no-op
        if existing and existing["side"] == new_side:
            msg = f"Already {existing['side']} {coin} — duplicate signal ignored"
            log.result = msg
            log.success = 1
            db.add(log)
            await db.commit()
            return WebhookResponse(success=True, message=msg)

        # Opposite-side = close ENTIRE position (signal + manual), then open fresh at strategy size
        close_pnl = 0.0
        if existing:
            close_side = "sell" if existing["side"] == "long" else "buy"
            close_result = await engine.execute_order_with_fallback(
                coin, close_side, existing["size"]
            )
            if not close_result.success:
                raise ValueError(f"Close failed: {close_result.message}")

            # Calculate PnL
            if existing["side"] == "long":
                close_pnl = (close_result.filled_price - existing["entry_price"]) * existing["size"]
            else:
                close_pnl = (existing["entry_price"] - close_result.filled_price) * existing["size"]
            close_pnl = round(close_pnl, 4)

            closed_notional = pt.total_size if (pt and pt.total_size > 0) else existing["notional"]

            # Log the close trade
            db.add(LiveTrade(
                coin=coin,
                action=f"close_{existing['side']}",
                origin=origin,
                size=closed_notional,
                price=close_result.filled_price,
                pnl=close_pnl,
                total_position_after=0.0,
                notes=f"Closed for {action} signal",
            ))

            await _update_asset_stats(
                db, coin, "close", close_result.filled_price,
                pnl=close_pnl, is_close=True,
            )

            asyncio.create_task(notifier.notify_trade_close(
                symbol=coin, side=existing["side"],
                quantity=existing["size"], entry_price=existing["entry_price"],
                exit_price=close_result.filled_price,
                pnl=close_pnl,
                strategy_name="Live", leverage=leverage,
            ))

        # Calculate quantity for NEW position at strategy size
        quantity = payload.quantity or 0.0
        if quantity <= 0:
            if fixed_amount and fixed_amount > 0:
                notional = fixed_amount * leverage
            else:
                account_balance = await engine.get_balance()
                if account_balance <= 0:
                    raise ValueError("Account balance is zero or unavailable")
                size_pct = payload.size_pct or settings.default_size_pct
                if settings.use_max_size and not payload.size_pct:
                    notional = account_balance * (settings.default_max_position_pct / 100)
                else:
                    margin = account_balance * (size_pct / 100)
                    notional = margin * leverage
            quantity = notional / price

        quantity = round(quantity, sz_decimals)
        if quantity <= 0:
            raise ValueError("Calculated quantity is zero after rounding to szDecimals")

        if quantity * price < 10.0:
            raise ValueError(
                f"Order notional ${quantity * price:.2f} below Hyperliquid minimum of $10"
            )

        # Risk check
        account_balance_for_risk = await engine.get_balance() if not fixed_amount else 0
        allowed, reason = await risk_manager.check_trade_live(
            db, coin, quantity, price, account_balance_for_risk,
            leverage_override=leverage,
            max_position_pct_override=asset_cfg.max_position_pct if asset_cfg else None,
        )
        if not allowed:
            asyncio.create_task(notifier.notify_risk_breach(
                strategy_name="Live", symbol=coin, reason=reason,
            ))
            raise ValueError(f"Risk check failed: {reason}")

        # Execute new position
        result = await engine.execute_order_with_fallback(coin, action, quantity)
        if not result.success:
            raise ValueError(result.message)

        fill_price = result.filled_price or price
        filled_notional = fill_price * (result.quantity or quantity)

        # Update position tracking
        now = dt.datetime.utcnow()
        if pt is None:
            pt = PositionTracking(coin=coin)
            db.add(pt)

        pt.direction = new_side
        pt.signal_size = filled_notional
        pt.manual_size = 0.0
        pt.total_size = filled_notional
        pt.entry_price = fill_price
        pt.opened_at = now
        pt.origin = origin
        pt.last_modified_at = now
        pt.last_modified_by = origin

        # Log the open trade
        trade_action = f"open_{new_side}" if not existing else f"flip_to_{new_side}"
        db.add(LiveTrade(
            coin=coin,
            action=trade_action,
            origin=origin,
            size=filled_notional,
            price=fill_price,
            pnl=None,
            total_position_after=filled_notional,
            notes=payload.message or f"{origin.title()} {new_side} signal",
        ))

        await _update_asset_stats(db, coin, new_side, fill_price)

        asyncio.create_task(notifier.notify_trade_open(
            symbol=coin, side=new_side, quantity=result.quantity,
            price=fill_price, strategy_name="Live",
            fill_type=result.fill_type, leverage=leverage,
        ))

        # Post-trade leverage verification (fire-and-forget)
        from app.services.leverage_manager import verify_leverage_post_trade
        asyncio.create_task(verify_leverage_post_trade(coin))

        msg = result.message
        if existing:
            pnl_sign = "+" if close_pnl >= 0 else ""
            msg = f"Flipped {existing['side']}→{new_side} {coin} (P&L: {pnl_sign}${close_pnl:.2f}) | {msg}"
        log.result = msg
        log.success = 1
        db.add(log)
        await db.commit()
        return WebhookResponse(success=True, message=msg)

    elif action == "close":
        # Close position for this symbol if one exists. Never opens a new position.
        from app.services.hl_account import hl_account
        hl_positions = await hl_account.get_open_positions()
        matching = [p for p in hl_positions if p["symbol"] == coin]
        if not matching:
            log.result = f"No open position for {coin} — nothing to close"
            log.success = 1
            db.add(log)
            await db.commit()
            return WebhookResponse(success=True, message=f"No open position for {coin}")

        pos = matching[0]
        close_side = "sell" if pos["side"] == "long" else "buy"
        result = await engine.execute_order_with_fallback(coin, close_side, pos["size"])
        if not result.success:
            raise ValueError(result.message)

        if pos["side"] == "long":
            pnl = (result.filled_price - pos["entry_price"]) * pos["size"]
        else:
            pnl = (pos["entry_price"] - result.filled_price) * pos["size"]
        pnl = round(pnl, 4)

        if pt:
            db.add(LiveTrade(
                coin=coin, action=f"close_{pos['side']}", origin="close_signal",
                size=pt.total_size, price=result.filled_price,
                pnl=pnl, total_position_after=0.0,
                notes=payload.message or "Close signal",
            ))
            pt.direction = None
            pt.signal_size = 0.0
            pt.manual_size = 0.0
            pt.total_size = 0.0
            pt.entry_price = None
            pt.opened_at = None
            pt.last_modified_at = dt.datetime.utcnow()
            pt.last_modified_by = "close_signal"

        await _update_asset_stats(db, coin, "close", result.filled_price, pnl=pnl, is_close=True)

        pnl_sign = "+" if pnl >= 0 else ""
        close_msg = (
            f"\U0001f534 CLOSE \u2014 {coin} \u2014 Position closed @ ${result.filled_price:,.2f}\n"
            f"P&L: {pnl_sign}${pnl:,.2f} \u2014 Strategy B exit"
        )
        asyncio.create_task(notifier._send_telegram(close_msg))

        msg = f"Closed {pos['side']} {coin} @ {result.filled_price:.4f} | P&L: {pnl_sign}${pnl:.2f}"
        log.result = msg
        log.success = 1
        db.add(log)
        await db.commit()
        return WebhookResponse(success=True, message=msg)

    elif action in ("close_long", "close_short", "close_all"):
        from app.services.hl_account import hl_account
        hl_positions = await hl_account.get_open_positions()

        if action == "close_all":
            if not hl_positions:
                log.result = "No positions to close"
                log.success = 0
                db.add(log)
                await db.commit()
                return WebhookResponse(success=False, message="No positions to close")

            results = []
            for pos in hl_positions:
                close_side = "sell" if pos["side"] == "long" else "buy"
                r = await engine.execute_order_with_fallback(
                    pos["symbol"], close_side, pos["size"]
                )
                coin_sym = pos["symbol"]
                if r.success:
                    # Update tracking
                    pt_r = await db.execute(
                        select(PositionTracking).where(PositionTracking.coin == coin_sym)
                    )
                    pt_row = pt_r.scalar_one_or_none()
                    if pt_row:
                        pt_row.direction = None
                        pt_row.signal_size = 0.0
                        pt_row.manual_size = 0.0
                        pt_row.total_size = 0.0
                        pt_row.entry_price = None
                        pt_row.opened_at = None
                        pt_row.last_modified_at = dt.datetime.utcnow()
                        pt_row.last_modified_by = origin
                results.append(f"{coin_sym}: {'OK' if r.success else r.message}")

            msg = f"Closed all: {', '.join(results)}"
            log.result = msg
            log.success = 1
            db.add(log)
            await db.commit()
            return WebhookResponse(success=True, message=msg)

        # Close specific symbol
        matching = [p for p in hl_positions if p["symbol"] == coin]
        if not matching:
            log.result = f"No open position for {coin}"
            log.success = 0
            db.add(log)
            await db.commit()
            return WebhookResponse(success=False, message=f"No open position for {coin}")

        pos = matching[0]
        close_side = "sell" if pos["side"] == "long" else "buy"
        result = await engine.execute_order_with_fallback(
            coin, close_side, pos["size"]
        )
        if not result.success:
            raise ValueError(result.message)

        # PnL
        if pos["side"] == "long":
            pnl = (result.filled_price - pos["entry_price"]) * pos["size"]
        else:
            pnl = (pos["entry_price"] - result.filled_price) * pos["size"]
        pnl = round(pnl, 4)

        # Update tracking
        if pt:
            db.add(LiveTrade(
                coin=coin, action=f"close_{pos['side']}", origin=origin,
                size=pt.total_size, price=result.filled_price,
                pnl=pnl, total_position_after=0.0,
                notes=payload.message or f"Signal close",
            ))
            pt.direction = None
            pt.signal_size = 0.0
            pt.manual_size = 0.0
            pt.total_size = 0.0
            pt.entry_price = None
            pt.opened_at = None
            pt.last_modified_at = dt.datetime.utcnow()
            pt.last_modified_by = origin

        await _update_asset_stats(
            db, coin, "close", result.filled_price,
            pnl=pnl, is_close=True,
        )

        asyncio.create_task(notifier.notify_trade_close(
            symbol=coin, side=pos["side"],
            quantity=pos["size"], entry_price=pos["entry_price"],
            exit_price=result.filled_price,
            pnl=pnl,
            strategy_name="Live", leverage=leverage,
        ))

        log.result = result.message
        log.success = 1
        db.add(log)
        await db.commit()
        return WebhookResponse(success=True, message=result.message)

    else:
        raise ValueError(f"Unknown action: {action}")


async def _update_asset_stats(
    db: AsyncSession, coin: str, direction: str, price: float, pnl: float = 0.0, is_close: bool = False
):
    """Update asset_configs stats after a trade."""
    result = await db.execute(
        select(AssetConfig).where(AssetConfig.coin == coin)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        return
    import datetime as dt
    asset.total_trades += 1
    if is_close and pnl > 0:
        asset.winning_trades += 1
    if is_close:
        asset.total_pnl += pnl
    asset.last_trade_at = dt.datetime.utcnow()
    asset.last_trade_direction = direction
    asset.last_trade_price = price
    asset.updated_at = dt.datetime.utcnow()


async def _get_existing_position(
    db: AsyncSession, strategy_id: int, symbol: str
) -> Position | None:
    stmt = select(Position).where(
        Position.strategy_id == strategy_id,
        Position.symbol == symbol,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
