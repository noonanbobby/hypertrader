from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    trading_mode: Literal["paper", "live"] = "paper"
    webhook_secret: str = "change-me"
    database_url: str = "sqlite+aiosqlite:///./hypertrader.db"

    # Paper Trading
    initial_balance: float = 10000.0
    slippage_pct: float = 0.05
    maker_fee_pct: float = 0.02
    taker_fee_pct: float = 0.05
    leverage: float = 10.0

    # Risk Defaults
    default_max_position_pct: float = 25.0
    default_max_drawdown_pct: float = 10.0
    default_daily_loss_limit: float = 500.0

    # Hyperliquid
    hl_api_key: str = ""
    hl_api_secret: str = ""
    hl_vault_address: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
