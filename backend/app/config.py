from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    """Loads from .env — used for infrastructure + initial seed values."""
    trading_mode: Literal["paper", "live"] = "paper"
    webhook_secret: str = "change-me"
    database_url: str = "sqlite+aiosqlite:///./hypertrader.db"

    # Paper Trading
    initial_balance: float = 10000.0
    slippage_pct: float = 0.05
    maker_fee_pct: float = 0.02
    taker_fee_pct: float = 0.05
    leverage: float = 10.0

    # Position Sizing
    default_size_pct: float = 10.0

    # Risk Defaults
    default_max_position_pct: float = 25.0
    default_max_drawdown_pct: float = 10.0
    default_daily_loss_limit: float = 500.0

    # Limit Orders
    use_limit_orders: bool = True
    limit_order_timeout_sec: float = 30.0
    limit_order_offset_pct: float = 0.0

    # Telegram Notifications
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_chat_id_2: str = ""
    notify_trade_open: bool = True
    notify_trade_close: bool = True
    notify_risk_breach: bool = True

    # Emergency Pause
    trading_paused: bool = False

    # Hyperliquid
    hl_api_key: str = ""
    hl_api_secret: str = ""
    hl_vault_address: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


_env_settings = Settings()

# Fields that live in the DB (runtime-configurable)
RUNTIME_FIELDS = [
    "trading_mode", "webhook_secret", "leverage",
    "initial_balance", "slippage_pct", "maker_fee_pct", "taker_fee_pct",
    "use_limit_orders", "limit_order_timeout_sec", "limit_order_offset_pct",
    "default_size_pct",
    "default_max_position_pct", "default_max_drawdown_pct", "default_daily_loss_limit",
    "hl_api_key", "hl_api_secret", "hl_vault_address",
    "telegram_enabled", "telegram_bot_token", "telegram_chat_id", "telegram_chat_id_2",
    "notify_trade_open", "notify_trade_close", "notify_risk_breach",
    "trading_paused",
]


class RuntimeSettings:
    """Drop-in replacement for the old Settings singleton.

    Infrastructure fields (database_url, host, port, frontend_url) come from
    .env and never change at runtime.  All trading/risk/API fields are loaded
    from the DB after startup and can be changed via the settings API.
    """

    def __init__(self, env: Settings):
        # Copy all .env values as starting point
        for field in env.model_fields:
            setattr(self, field, getattr(env, field))

    def update_from_db_row(self, row):
        """Sync in-memory values from a DB AppSettings row."""
        for field in RUNTIME_FIELDS:
            setattr(self, field, getattr(row, field))


settings = RuntimeSettings(_env_settings)
