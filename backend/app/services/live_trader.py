from typing import Optional
from app.services.trading_engine import TradingEngine, OrderResult


class LiveTrader(TradingEngine):
    """Stub for Hyperliquid live trading. To be implemented."""

    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        if order_type == "limit" and price is not None:
            return await self._execute_limit(symbol, side, quantity, price)
        return await self._execute_market(symbol, side, quantity)

    async def _execute_market(
        self, symbol: str, side: str, quantity: float
    ) -> OrderResult:
        # TODO: Hyperliquid SDK market order
        return OrderResult(
            success=False,
            message="Live market trading not yet implemented",
        )

    async def _execute_limit(
        self, symbol: str, side: str, quantity: float, price: float
    ) -> OrderResult:
        # TODO: Hyperliquid SDK limit order + poll for fill status
        return OrderResult(
            success=False,
            message="Live limit trading not yet implemented",
        )

    async def get_balance(self) -> float:
        return 0.0

    async def get_current_price(self, symbol: str) -> Optional[float]:
        from app.services.market_data import market_data
        return await market_data.get_mid_price(symbol)
