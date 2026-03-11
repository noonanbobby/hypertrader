from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[int] = None
    filled_price: Optional[float] = None
    quantity: Optional[float] = None
    fees: float = 0.0
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


def create_engine(mode: str) -> TradingEngine:
    if mode == "paper":
        from app.services.paper_trader import PaperTrader
        return PaperTrader()
    elif mode == "live":
        from app.services.live_trader import LiveTrader
        return LiveTrader()
    else:
        raise ValueError(f"Unknown trading mode: {mode}")
