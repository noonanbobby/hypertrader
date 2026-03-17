from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal


# --- Webhook ---
class WebhookPayload(BaseModel):
    secret: str
    strategy: Optional[str] = None  # required for paper, ignored for live
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
    fill_type: str = "taker"

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


# --- Settings ---
def _mask_secret(value: str) -> str:
    if not value or len(value) <= 4:
        return "****" if value else ""
    return "*" * (len(value) - 4) + value[-4:]


class SettingsResponse(BaseModel):
    trading_mode: str
    webhook_secret: str
    webhook_url: str
    leverage: float
    initial_balance: float
    slippage_pct: float
    maker_fee_pct: float
    taker_fee_pct: float
    use_limit_orders: bool
    limit_order_timeout_sec: float
    limit_order_offset_pct: float
    default_size_pct: float
    use_max_size: bool
    default_max_position_pct: float
    default_max_drawdown_pct: float
    default_daily_loss_limit: float
    hl_api_key: str
    hl_api_secret: str
    hl_vault_address: str
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_chat_id_2: str
    notify_trade_open: bool
    notify_trade_close: bool
    notify_risk_breach: bool
    trading_paused: bool
    updated_at: datetime

    @classmethod
    def from_row(cls, row) -> "SettingsResponse":
        return cls(
            trading_mode=row.trading_mode,
            webhook_secret=_mask_secret(row.webhook_secret),
            webhook_url=row.webhook_url,
            leverage=row.leverage,
            initial_balance=row.initial_balance,
            slippage_pct=row.slippage_pct,
            maker_fee_pct=row.maker_fee_pct,
            taker_fee_pct=row.taker_fee_pct,
            use_limit_orders=row.use_limit_orders,
            limit_order_timeout_sec=row.limit_order_timeout_sec,
            limit_order_offset_pct=row.limit_order_offset_pct,
            default_size_pct=row.default_size_pct,
            use_max_size=row.use_max_size,
            default_max_position_pct=row.default_max_position_pct,
            default_max_drawdown_pct=row.default_max_drawdown_pct,
            default_daily_loss_limit=row.default_daily_loss_limit,
            hl_api_key=_mask_secret(row.hl_api_key),
            hl_api_secret=_mask_secret(row.hl_api_secret),
            hl_vault_address=row.hl_vault_address,
            telegram_enabled=row.telegram_enabled,
            telegram_bot_token=row.telegram_bot_token,
            telegram_chat_id=row.telegram_chat_id,
            telegram_chat_id_2=row.telegram_chat_id_2,
            notify_trade_open=row.notify_trade_open,
            notify_trade_close=row.notify_trade_close,
            notify_risk_breach=row.notify_risk_breach,
            trading_paused=row.trading_paused,
            updated_at=row.updated_at,
        )


# --- System Status ---
class ServiceCheck(BaseModel):
    name: str
    status: Literal["ok", "degraded", "down"]
    message: str = ""
    url: Optional[str] = None


class SystemStatus(BaseModel):
    backend: ServiceCheck
    ngrok: ServiceCheck
    websocket: ServiceCheck
    telegram: ServiceCheck
    checked_at: datetime


# --- Hyperliquid Live ---
class HLPortfolio(BaseModel):
    account_value: float
    total_margin_used: float
    total_unrealized_pnl: float
    available_balance: float
    perps_balance: float = 0.0
    spot_balance: float = 0.0


class HLPosition(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: float
    liquidation_price: Optional[float] = None
    margin_used: float
    notional: float


class HLFill(BaseModel):
    symbol: str
    side: str
    size: float
    price: float
    fee: float
    time: int  # epoch ms from HL
    closed_pnl: float


class HLStatus(BaseModel):
    configured: bool
    connected: bool
    account_value: Optional[float] = None


# --- Asset Config ---
class AssetConfigResponse(BaseModel):
    id: int
    coin: str
    display_name: str
    enabled: bool
    fixed_trade_amount_usd: float
    leverage: int
    max_leverage: int
    max_position_pct: float
    st_atr_period: int
    st_multiplier: float
    st_source: str
    htf_timeframe: str
    htf_st_atr_period: int
    htf_st_multiplier: float
    adx_period: int
    adx_minimum: float
    adx_rising_required: bool
    squeeze_block: bool
    sqz_bb_length: int
    sqz_bb_mult: float
    sqz_kc_length: int
    sqz_kc_mult: float
    total_trades: int
    winning_trades: int
    total_pnl: float
    last_trade_at: Optional[datetime] = None
    last_trade_direction: Optional[str] = None
    last_trade_price: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssetConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    fixed_trade_amount_usd: Optional[float] = Field(default=None, gt=0)
    leverage: Optional[int] = Field(default=None, gt=0, le=100)
    max_position_pct: Optional[float] = Field(default=None, gt=0, le=100)
    st_atr_period: Optional[int] = Field(default=None, gt=0)
    st_multiplier: Optional[float] = Field(default=None, gt=0)
    st_source: Optional[str] = None
    htf_timeframe: Optional[str] = None
    htf_st_atr_period: Optional[int] = Field(default=None, gt=0)
    htf_st_multiplier: Optional[float] = Field(default=None, gt=0)
    adx_period: Optional[int] = Field(default=None, gt=0)
    adx_minimum: Optional[float] = Field(default=None, ge=0)
    adx_rising_required: Optional[bool] = None
    squeeze_block: Optional[bool] = None
    sqz_bb_length: Optional[int] = Field(default=None, gt=0)
    sqz_bb_mult: Optional[float] = Field(default=None, gt=0)
    sqz_kc_length: Optional[int] = Field(default=None, gt=0)
    sqz_kc_mult: Optional[float] = Field(default=None, gt=0)
    notes: Optional[str] = None


# --- Position Tracking ---
class PositionTrackingResponse(BaseModel):
    id: int
    coin: str
    direction: Optional[str] = None
    signal_size: float = 0.0
    manual_size: float = 0.0
    total_size: float = 0.0
    entry_price: Optional[float] = None
    opened_at: Optional[datetime] = None
    origin: Optional[str] = None
    last_modified_at: Optional[datetime] = None
    last_modified_by: Optional[str] = None
    # Enriched from live data
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    leverage: Optional[int] = None
    notional: Optional[float] = None
    held_duration: Optional[str] = None

    model_config = {"from_attributes": True}


class PositionOpenRequest(BaseModel):
    direction: Literal["long", "short"]
    amount_usd: float = Field(gt=0)


class PositionAddRequest(BaseModel):
    add_pct: float = Field(gt=0, le=100)


class PositionReduceRequest(BaseModel):
    reduce_pct: float = Field(gt=0, le=100)


class PositionActionResponse(BaseModel):
    success: bool
    message: str
    pnl: Optional[float] = None
    held_duration: Optional[str] = None
    position: Optional[PositionTrackingResponse] = None


# --- Live Trade Log ---
class LiveTradeResponse(BaseModel):
    id: int
    coin: str
    action: str
    origin: str
    size: float
    price: float
    pnl: Optional[float] = None
    total_position_after: float
    timestamp: datetime
    notes: Optional[str] = None

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    trading_mode: Optional[Literal["paper", "live"]] = None
    webhook_secret: Optional[str] = None
    webhook_url: Optional[str] = None
    leverage: Optional[float] = Field(default=None, gt=0, le=100)
    initial_balance: Optional[float] = Field(default=None, gt=0)
    slippage_pct: Optional[float] = Field(default=None, ge=0, le=10)
    maker_fee_pct: Optional[float] = Field(default=None, ge=0, le=10)
    taker_fee_pct: Optional[float] = Field(default=None, ge=0, le=10)
    use_limit_orders: Optional[bool] = None
    limit_order_timeout_sec: Optional[float] = Field(default=None, gt=0, le=300)
    limit_order_offset_pct: Optional[float] = Field(default=None, ge=0, le=5)
    default_size_pct: Optional[float] = Field(default=None, gt=0, le=100)
    use_max_size: Optional[bool] = None
    default_max_position_pct: Optional[float] = Field(default=None, gt=0, le=100)
    default_max_drawdown_pct: Optional[float] = Field(default=None, gt=0, le=100)
    default_daily_loss_limit: Optional[float] = Field(default=None, gt=0)
    hl_api_key: Optional[str] = None
    hl_api_secret: Optional[str] = None
    hl_vault_address: Optional[str] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_chat_id_2: Optional[str] = None
    notify_trade_open: Optional[bool] = None
    notify_trade_close: Optional[bool] = None
    notify_risk_breach: Optional[bool] = None
    trading_paused: Optional[bool] = None
