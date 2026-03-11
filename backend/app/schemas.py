from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# --- Webhook ---
class WebhookPayload(BaseModel):
    secret: str
    strategy: str
    action: str  # buy, sell, close_long, close_short, close_all
    symbol: str
    quantity: Optional[float] = None
    size_pct: Optional[float] = None  # % of strategy equity to use (e.g. 10 = 10%)
    price: Optional[float] = None
    message: str = ""


class WebhookResponse(BaseModel):
    success: bool
    message: str
    trade_id: Optional[int] = None


# --- Strategy ---
class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    allocated_capital: float = Field(default=10000.0, gt=0)
    max_position_pct: float = Field(default=25.0, gt=0, le=100)
    max_drawdown_pct: float = Field(default=10.0, gt=0, le=100)


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    allocated_capital: Optional[float] = None
    max_position_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    status: Optional[str] = None


class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str
    allocated_capital: float
    current_equity: float
    max_position_pct: float
    max_drawdown_pct: float
    status: str
    total_trades: int
    winning_trades: int
    total_pnl: float
    peak_equity: float
    win_rate: float = 0.0
    current_drawdown: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Trade ---
class TradeResponse(BaseModel):
    id: int
    strategy_id: int
    strategy_name: str = ""
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    notional_value: float = 0.0  # entry_price * quantity (full position size)
    margin_used: float = 0.0     # notional / leverage (actual capital spent)
    leverage: float = 10.0
    realized_pnl: float
    fees: float
    status: str
    entry_time: datetime
    exit_time: Optional[datetime]
    message: str

    model_config = {"from_attributes": True}


# --- Position ---
class PositionResponse(BaseModel):
    id: int
    strategy_id: int
    strategy_name: str = ""
    symbol: str
    side: str
    entry_price: float
    quantity: float
    current_price: float
    unrealized_pnl: float
    pnl_pct: float = 0.0
    notional_value: float = 0.0   # full position size
    margin_used: float = 0.0      # notional / leverage
    leverage: float = 10.0
    opened_at: datetime

    model_config = {"from_attributes": True}


# --- Dashboard ---
class DashboardStats(BaseModel):
    total_equity: float
    total_pnl: float
    daily_pnl: float
    weekly_pnl: float
    monthly_pnl: float
    open_positions: int
    active_strategies: int
    total_trades: int
    win_rate: float
    best_trade: float
    worst_trade: float
    trading_mode: str


class PnlDataPoint(BaseModel):
    timestamp: datetime
    equity: float
    drawdown: float


# --- Analytics ---
class AnalyticsResponse(BaseModel):
    equity_curve: list[PnlDataPoint]
    monthly_returns: dict[str, float]
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    avg_trade_duration_hours: float


# --- WebSocket Events ---
class WSEvent(BaseModel):
    event: str
    data: dict


# --- Order ---
class OrderResponse(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    side: str
    order_type: str
    price: Optional[float]
    quantity: float
    filled_price: Optional[float]
    status: str
    created_at: datetime
    filled_at: Optional[datetime]

    model_config = {"from_attributes": True}
