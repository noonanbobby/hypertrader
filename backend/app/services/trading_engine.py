from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[int] = None
    filled_price: Optional[float] = None
    quantity: Optional[float] = None
    fees: float = 0.0
    message: str = ""
    fill_type: str = "taker"


@dataclass
class FlipResult:
    """Result of a position flip (close existing + open new)."""
    success: bool
    close_price: Optional[float] = None
    close_qty: Optional[float] = None
    close_fees: float = 0.0
    open_price: Optional[float] = None
    open_qty: Optional[float] = None
    open_fees: float = 0.0
    fill_type: str = "taker"
    message: str = ""


class TradingEngine(ABC):
    @abstractmethod
    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        """Execute a trade order."""
        pass

    @abstractmethod
    async def get_balance(self) -> float:
        """Get current account balance."""
        pass

    @abstractmethod
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol."""
        pass

    async def execute_flip(
        self,
        symbol: str,
        new_side: str,
        close_qty: float,
        open_qty: float,
    ) -> FlipResult:
        """Flip a position: close existing + open new.

        Default implementation uses two separate orders (close then open).
        LiveTrader overrides with single-order netting for Hyperliquid.
        """
        # When flipping, close direction = new signal direction:
        # sell to close long (when going short), buy to close short (when going long)
        close_result = await self.execute_order_with_fallback(
            symbol, new_side, close_qty
        )
        if not close_result.success:
            return FlipResult(success=False, message=f"Close failed: {close_result.message}")

        # Open new position
        open_result = await self.execute_order_with_fallback(
            symbol, new_side, open_qty
        )
        if not open_result.success:
            return FlipResult(
                success=False,
                close_price=close_result.filled_price,
                close_qty=close_result.quantity,
                close_fees=close_result.fees,
                message=f"Closed but open failed: {open_result.message}",
            )

        return FlipResult(
            success=True,
            close_price=close_result.filled_price,
            close_qty=close_result.quantity,
            close_fees=close_result.fees,
            open_price=open_result.filled_price,
            open_qty=open_result.quantity,
            open_fees=open_result.fees,
            fill_type=open_result.fill_type,
            message=f"Flip: closed {close_qty} @ {close_result.filled_price:.4f}, "
                    f"opened {open_result.quantity} @ {open_result.filled_price:.4f}",
        )

    async def execute_order_with_fallback(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> OrderResult:
        """Try limit order first, fall back to market order on timeout/failure."""
        from app.config import settings

        if not settings.use_limit_orders:
            result = await self.execute_order(symbol, side, quantity, order_type="market")
            result.fill_type = "taker"
            return result

        # Get mid price and calculate limit price with offset
        mid_price = await self.get_current_price(symbol)
        if mid_price is None:
            return OrderResult(success=False, message=f"Cannot get price for {symbol}")

        offset = settings.limit_order_offset_pct / 100
        if side in ("buy", "long"):
            limit_price = mid_price * (1 + offset)  # slightly above mid for buys
        else:
            limit_price = mid_price * (1 - offset)  # slightly below mid for sells

        # Attempt limit order
        result = await self.execute_order(
            symbol, side, quantity, order_type="limit", price=round(limit_price, 6)
        )

        if result.success:
            result.fill_type = "maker"
            return result

        # Fallback to market order
        market_result = await self.execute_order(symbol, side, quantity, order_type="market")
        market_result.fill_type = "taker"
        market_result.message = f"Limit unfilled, market fallback: {market_result.message}"
        return market_result


def create_engine(mode: str) -> TradingEngine:
    if mode == "paper":
        from app.services.paper_trader import PaperTrader
        return PaperTrader()
    elif mode == "live":
        from app.services.live_trader import LiveTrader
        return LiveTrader()
    else:
        raise ValueError(f"Unknown trading mode: {mode}")
