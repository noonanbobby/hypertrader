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
        return OrderResult(
            success=False,
            message="Live trading not yet implemented",
        )

    async def get_balance(self) -> float:
        return 0.0

    async def get_current_price(self, symbol: str) -> Optional[float]:
        from app.services.market_data import market_data
        return await market_data.get_mid_price(symbol)
