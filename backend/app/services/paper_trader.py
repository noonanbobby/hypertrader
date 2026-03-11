import random
import asyncio
from typing import Optional
from app.config import settings
from app.services.trading_engine import TradingEngine, OrderResult
from app.services.market_data import market_data


class PaperTrader(TradingEngine):
    def __init__(self):
        self._balance = settings.initial_balance
        self._slippage_pct = settings.slippage_pct
        self._taker_fee_pct = settings.taker_fee_pct

    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        """Route to market or limit simulation."""
        if order_type == "limit" and price is not None:
            return await self._execute_limit(symbol, side, quantity, price)
        return await self._execute_market(symbol, side, quantity)

    async def _execute_market(
        self, symbol: str, side: str, quantity: float
    ) -> OrderResult:
        """Simulate market order with slippage and taker fees."""
        mid_price = await self.get_current_price(symbol)
        if mid_price is None:
            return OrderResult(success=False, message=f"Cannot get price for {symbol}")

        slippage_mult = 1 + (self._slippage_pct / 100)
        if side in ("buy", "long"):
            filled_price = mid_price * slippage_mult
        else:
            filled_price = mid_price / slippage_mult

        notional = filled_price * quantity
        fees = notional * (self._taker_fee_pct / 100)

        return OrderResult(
            success=True,
            filled_price=round(filled_price, 6),
            quantity=quantity,
            fees=round(fees, 6),
            message=f"Paper market fill: {side} {quantity} {symbol} @ {filled_price:.4f}",
        )

    async def _execute_limit(
        self, symbol: str, side: str, quantity: float, limit_price: float
    ) -> OrderResult:
        """Simulate limit order: probabilistic fill at exact limit price, maker fee."""
        mid_price = await self.get_current_price(symbol)
        if mid_price is None:
            return OrderResult(success=False, message=f"Cannot get price for {symbol}")

        # Base fill probability ~65% at mid, higher if aggressive (crossing spread)
        spread_pct = abs(limit_price - mid_price) / mid_price * 100 if mid_price else 0
        if side in ("buy", "long"):
            # Buying above mid = aggressive = higher fill chance
            if limit_price >= mid_price:
                fill_prob = 0.65 + min(spread_pct * 10, 0.30)
            else:
                fill_prob = max(0.65 - spread_pct * 10, 0.10)
        else:
            # Selling below mid = aggressive = higher fill chance
            if limit_price <= mid_price:
                fill_prob = 0.65 + min(spread_pct * 10, 0.30)
            else:
                fill_prob = max(0.65 - spread_pct * 10, 0.10)

        # Simulate a brief wait (1-5s in paper mode for fast response)
        await asyncio.sleep(random.uniform(1.0, 5.0))

        if random.random() > fill_prob:
            return OrderResult(
                success=False,
                message=f"Paper limit order not filled: {side} {quantity} {symbol} @ {limit_price:.4f}",
            )

        # Filled at exact limit price, no slippage, maker fee
        maker_fee_pct = settings.maker_fee_pct
        notional = limit_price * quantity
        fees = notional * (maker_fee_pct / 100)

        return OrderResult(
            success=True,
            filled_price=round(limit_price, 6),
            quantity=quantity,
            fees=round(fees, 6),
            message=f"Paper limit fill: {side} {quantity} {symbol} @ {limit_price:.4f} (maker)",
        )

    async def get_balance(self) -> float:
        return self._balance

    async def get_current_price(self, symbol: str) -> Optional[float]:
        return await market_data.get_mid_price(symbol)
