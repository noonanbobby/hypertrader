import datetime as dt
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, Text, Boolean, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base


class StrategyStatus(str, enum.Enum):
    active = "active"
    paused = "paused"


class TradeSide(str, enum.Enum):
    long = "long"
    short = "short"


class TradeStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    filled = "filled"
    cancelled = "cancelled"
    rejected = "rejected"


class OrderType(str, enum.Enum):
    market = "market"
    limit = "limit"


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    allocated_capital: Mapped[float] = mapped_column(Float, default=10000.0)
    current_equity: Mapped[float] = mapped_column(Float, default=10000.0)
    max_position_pct: Mapped[float] = mapped_column(Float, default=25.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=10.0)
    status: Mapped[str] = mapped_column(String(20), default=StrategyStatus.active.value)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    peak_equity: Mapped[float] = mapped_column(Float, default=10000.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    trades: Mapped[list["Trade"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")
    positions: Mapped[list["Position"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")
    equity_snapshots: Mapped[list["EquitySnapshot"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(10), default=TradeStatus.open.value)
    entry_time: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    exit_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    fill_type: Mapped[str] = mapped_column(String(10), default="taker")

    strategy: Mapped["Strategy"] = relationship(back_populates="trades")


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    strategy: Mapped["Strategy"] = relationship(back_populates="positions")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(10), default=OrderType.market.value)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    filled_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=OrderStatus.pending.value)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    filled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    strategy: Mapped["Strategy"] = relationship(back_populates="orders")


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id"), nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    strategy: Mapped["Strategy"] = relationship(back_populates="equity_snapshots")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    trading_mode: Mapped[str] = mapped_column(String(10), default="paper")
    webhook_secret: Mapped[str] = mapped_column(String(255), default="change-me")
    leverage: Mapped[float] = mapped_column(Float, default=10.0)
    initial_balance: Mapped[float] = mapped_column(Float, default=10000.0)
    slippage_pct: Mapped[float] = mapped_column(Float, default=0.05)
    maker_fee_pct: Mapped[float] = mapped_column(Float, default=0.02)
    taker_fee_pct: Mapped[float] = mapped_column(Float, default=0.05)
    default_max_position_pct: Mapped[float] = mapped_column(Float, default=25.0)
    default_max_drawdown_pct: Mapped[float] = mapped_column(Float, default=10.0)
    default_daily_loss_limit: Mapped[float] = mapped_column(Float, default=500.0)
    use_limit_orders: Mapped[bool] = mapped_column(Boolean, default=True)
    limit_order_timeout_sec: Mapped[float] = mapped_column(Float, default=30.0)
    limit_order_offset_pct: Mapped[float] = mapped_column(Float, default=0.0)
    default_size_pct: Mapped[float] = mapped_column(Float, default=10.0)
    hl_api_key: Mapped[str] = mapped_column(String(255), default="")
    hl_api_secret: Mapped[str] = mapped_column(String(255), default="")
    hl_vault_address: Mapped[str] = mapped_column(String(255), default="")
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_bot_token: Mapped[str] = mapped_column(String(255), default="")
    telegram_chat_id: Mapped[str] = mapped_column(String(255), default="")
    telegram_chat_id_2: Mapped[str] = mapped_column(String(255), default="")
    notify_trade_open: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_trade_close: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_risk_breach: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_action: Mapped[str] = mapped_column(String(50), default="")
    strategy_name: Mapped[str] = mapped_column(String(100), default="")
    symbol: Mapped[str] = mapped_column(String(20), default="")
    result: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[int] = mapped_column(Integer, default=1)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
