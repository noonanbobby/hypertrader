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
        """Simulate order execution with slippage and fees."""
        mid_price = await self.get_current_price(symbol)
        if mid_price is None:
            return OrderResult(success=False, message=f"Cannot get price for {symbol}")

        # Apply slippage
        slippage_mult = 1 + (self._slippage_pct / 100)
        if side in ("buy", "long"):
            filled_price = mid_price * slippage_mult
        else:
            filled_price = mid_price / slippage_mult

        # Calculate fees
        notional = filled_price * quantity
        fees = notional * (self._taker_fee_pct / 100)

        return OrderResult(
            success=True,
            filled_price=round(filled_price, 6),
            quantity=quantity,
            fees=round(fees, 6),
            message=f"Paper fill: {side} {quantity} {symbol} @ {filled_price:.4f}",
        )

    async def get_balance(self) -> float:
        return self._balance

    async def get_current_price(self, symbol: str) -> Optional[float]:
        return await market_data.get_mid_price(symbol)
