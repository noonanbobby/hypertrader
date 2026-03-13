"""Hyperliquid account service — reads portfolio, positions, and fills."""

import asyncio
import logging
from typing import Optional

from hyperliquid.info import Info
from hyperliquid.utils import constants

from app.config import settings

logger = logging.getLogger(__name__)


class HLAccountService:
    """Wraps hyperliquid.info.Info SDK calls for reading account state."""

    def __init__(self):
        self._info: Optional[Info] = None
        self._cached_key: str = ""
        self._cached_secret: str = ""

    def _get_info(self) -> Info:
        """Lazy-init Info client. Re-creates if credentials change."""
        key = settings.hl_api_key
        secret = settings.hl_api_secret

        if (
            self._info is not None
            and self._cached_key == key
            and self._cached_secret == secret
        ):
            return self._info

        if not key:
            raise ValueError("hl_api_key (master wallet address) is not set")

        self._info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self._cached_key = key
        self._cached_secret = secret

        logger.info("HLAccountService Info client initialized for %s", key[:10] + "...")
        return self._info

    def is_configured(self) -> bool:
        """Check if HL credentials are set."""
        return bool(settings.hl_api_key and settings.hl_api_secret)

    async def get_account_state(self) -> dict:
        """Get full user state from Hyperliquid."""
        info = self._get_info()
        address = settings.hl_api_key
        return await asyncio.to_thread(info.user_state, address)

    async def get_portfolio(self) -> dict:
        """Get portfolio summary from marginSummary."""
        state = await self.get_account_state()
        margin = state.get("marginSummary", {})
        return {
            "account_value": float(margin.get("accountValue", 0)),
            "total_margin_used": float(margin.get("totalMarginUsed", 0)),
            "total_unrealized_pnl": float(margin.get("totalNtlPos", 0)) - float(margin.get("accountValue", 0)) + float(margin.get("totalMarginUsed", 0)),
            "available_balance": float(margin.get("accountValue", 0)) - float(margin.get("totalMarginUsed", 0)),
        }

    async def get_open_positions(self) -> list[dict]:
        """Parse assetPositions from user_state."""
        state = await self.get_account_state()
        positions = []
        for item in state.get("assetPositions", []):
            pos = item.get("position", {})
            size = float(pos.get("szi", 0))
            if size == 0:
                continue
            entry_px = float(pos.get("entryPx", 0))
            mark_px = float(pos.get("positionValue", 0)) / abs(size) if size != 0 else 0
            unrealized_pnl = float(pos.get("unrealizedPnl", 0))
            margin_used = float(pos.get("marginUsed", 0))
            leverage_info = pos.get("leverage", {})
            leverage_val = float(leverage_info.get("value", 1)) if isinstance(leverage_info, dict) else float(leverage_info or 1)
            positions.append({
                "symbol": pos.get("coin", ""),
                "side": "long" if size > 0 else "short",
                "size": abs(size),
                "entry_price": entry_px,
                "mark_price": round(mark_px, 6),
                "unrealized_pnl": unrealized_pnl,
                "leverage": leverage_val,
                "liquidation_price": float(pos["liquidationPx"]) if pos.get("liquidationPx") else None,
                "margin_used": margin_used,
                "notional": abs(float(pos.get("positionValue", 0))),
            })
        return positions

    async def get_recent_fills(self, limit: int = 50) -> list[dict]:
        """Get recent fills from Hyperliquid."""
        info = self._get_info()
        address = settings.hl_api_key
        fills = await asyncio.to_thread(info.user_fills, address)
        # Sort by time descending and limit
        fills = sorted(fills, key=lambda f: f.get("time", 0), reverse=True)[:limit]
        result = []
        for f in fills:
            result.append({
                "symbol": f.get("coin", ""),
                "side": f.get("side", "").lower(),
                "size": float(f.get("sz", 0)),
                "price": float(f.get("px", 0)),
                "fee": float(f.get("fee", 0)),
                "time": f.get("time", 0),
                "closed_pnl": float(f.get("closedPnl", 0)),
            })
        return result


hl_account = HLAccountService()
