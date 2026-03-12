import asyncio
import logging
from typing import Optional

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

from app.config import settings
from app.services.trading_engine import TradingEngine, OrderResult
from app.services.market_data import market_data

logger = logging.getLogger(__name__)


class LiveTrader(TradingEngine):
    """Hyperliquid live trading via the official SDK."""

    def __init__(self):
        self._exchange: Optional[Exchange] = None
        self._info: Optional[Info] = None
        self._sz_decimals: dict[str, int] = {}
        self._cached_key: str = ""
        self._cached_secret: str = ""

    def _get_clients(self) -> tuple[Exchange, Info]:
        """Lazy-init SDK clients. Re-creates if credentials change."""
        key = settings.hl_api_key
        secret = settings.hl_api_secret

        if (
            self._exchange is not None
            and self._cached_key == key
            and self._cached_secret == secret
        ):
            return self._exchange, self._info

        if not secret:
            raise ValueError("hl_api_secret (agent wallet private key) is not set")
        if not key:
            raise ValueError("hl_api_key (master wallet address) is not set")

        wallet = eth_account.Account.from_key(secret)
        vault = settings.hl_vault_address or None

        self._exchange = Exchange(
            wallet,
            constants.MAINNET_API_URL,
            account_address=key,
            vault_address=vault,
        )
        self._info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self._cached_key = key
        self._cached_secret = secret

        logger.info("LiveTrader SDK clients initialized for %s", key[:10] + "...")
        return self._exchange, self._info

    def _normalize_coin(self, symbol: str) -> str:
        """Normalize symbol to Hyperliquid coin format (e.g. BTCUSDT -> BTC)."""
        coin = symbol.upper().replace("-PERP", "").replace("/USD", "")
        for suffix in ("USDC", "USDT", "USD", "PERP"):
            if coin.endswith(suffix) and len(coin) > len(suffix):
                coin = coin[: -len(suffix)]
                break
        return coin

    async def _get_sz_decimals(self, coin: str) -> int:
        """Fetch and cache szDecimals for a coin from exchange meta."""
        if coin in self._sz_decimals:
            return self._sz_decimals[coin]

        meta = await market_data.get_meta()
        if meta and "universe" in meta:
            for asset in meta["universe"]:
                self._sz_decimals[asset["name"]] = asset.get("szDecimals", 5)

        return self._sz_decimals.get(coin, 5)

    def _round_sz(self, sz: float, decimals: int) -> float:
        """Round size to allowed decimals."""
        return round(sz, decimals)

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
        """Execute a market order on Hyperliquid."""
        try:
            exchange, info = self._get_clients()
            coin = self._normalize_coin(symbol)
            is_buy = side in ("buy", "long")

            sz_dec = await self._get_sz_decimals(coin)
            sz = self._round_sz(quantity, sz_dec)
            if sz <= 0:
                return OrderResult(success=False, message="Quantity rounds to zero")

            # SDK is synchronous — run in thread
            response = await asyncio.to_thread(
                exchange.market_open, coin, is_buy, sz, None, 0.01
            )
            logger.info("Market order response: %s", response)

            return self._parse_order_response(response, coin, side, sz)

        except Exception as e:
            logger.exception("Market order failed for %s", symbol)
            return OrderResult(success=False, message=str(e))

    async def _execute_limit(
        self, symbol: str, side: str, quantity: float, price: float
    ) -> OrderResult:
        """Execute a limit order on Hyperliquid, poll for fill, cancel if timeout."""
        try:
            exchange, info = self._get_clients()
            coin = self._normalize_coin(symbol)
            is_buy = side in ("buy", "long")

            sz_dec = await self._get_sz_decimals(coin)
            sz = self._round_sz(quantity, sz_dec)
            if sz <= 0:
                return OrderResult(success=False, message="Quantity rounds to zero")

            # Round price to reasonable precision (8 significant figures)
            limit_px = float(f"{price:.8g}")

            order_type_spec = {"limit": {"tif": "Gtc"}}
            response = await asyncio.to_thread(
                exchange.order, coin, is_buy, sz, limit_px, order_type_spec
            )
            logger.info("Limit order response: %s", response)

            # Parse the response
            status = response.get("response", {}).get("data", {}).get("statuses", [{}])[0]

            # Immediately filled
            if "filled" in status:
                fill = status["filled"]
                avg_px = float(fill["avgPx"])
                total_sz = float(fill["totalSz"])
                notional = avg_px * total_sz
                fees = notional * (settings.maker_fee_pct / 100)
                return OrderResult(
                    success=True,
                    order_id=fill.get("oid"),
                    filled_price=avg_px,
                    quantity=total_sz,
                    fees=round(fees, 6),
                    fill_type="maker",
                    message=f"Limit filled: {side} {total_sz} {coin} @ {avg_px:.4f}",
                )

            # Resting — poll for fill
            if "resting" in status:
                oid = status["resting"]["oid"]
                return await self._poll_limit_order(
                    exchange, info, coin, oid, sz, side
                )

            # Error in status
            if "error" in status:
                return OrderResult(success=False, message=status["error"])

            return OrderResult(
                success=False, message=f"Unexpected order status: {status}"
            )

        except Exception as e:
            logger.exception("Limit order failed for %s", symbol)
            return OrderResult(success=False, message=str(e))

    async def _poll_limit_order(
        self,
        exchange: Exchange,
        info: Info,
        coin: str,
        oid: int,
        expected_sz: float,
        side: str,
    ) -> OrderResult:
        """Poll a resting limit order until filled or timeout, then cancel."""
        timeout = settings.limit_order_timeout_sec
        interval = 2.0
        elapsed = 0.0
        address = settings.hl_api_key

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                order_status = await asyncio.to_thread(
                    info.query_order_by_oid, address, oid
                )
                logger.debug("Order %s status: %s", oid, order_status)

                if order_status and order_status.get("order", {}).get("status") == "filled":
                    avg_px = float(order_status["order"]["limitPx"])
                    # Try to get actual fill price from order details
                    if "avgPx" in order_status.get("order", {}):
                        avg_px = float(order_status["order"]["avgPx"])
                    total_sz = float(order_status["order"].get("origSz", expected_sz))
                    notional = avg_px * total_sz
                    fees = notional * (settings.maker_fee_pct / 100)
                    return OrderResult(
                        success=True,
                        order_id=oid,
                        filled_price=avg_px,
                        quantity=total_sz,
                        fees=round(fees, 6),
                        fill_type="maker",
                        message=f"Limit filled (polled): {side} {total_sz} {coin} @ {avg_px:.4f}",
                    )
            except Exception as e:
                logger.warning("Error polling order %s: %s", oid, e)

        # Timeout — cancel the order
        try:
            await asyncio.to_thread(exchange.cancel, coin, oid)
            logger.info("Cancelled resting order %s after %.1fs timeout", oid, timeout)
        except Exception as e:
            logger.warning("Failed to cancel order %s: %s", oid, e)

        return OrderResult(
            success=False,
            message=f"Limit order {oid} not filled after {timeout}s, cancelled",
        )

    def _parse_order_response(
        self, response: dict, coin: str, side: str, sz: float
    ) -> OrderResult:
        """Parse SDK order response into OrderResult."""
        try:
            statuses = (
                response.get("response", {}).get("data", {}).get("statuses", [])
            )
            if not statuses:
                return OrderResult(
                    success=False, message=f"Empty response from exchange: {response}"
                )

            status = statuses[0]

            if "filled" in status:
                fill = status["filled"]
                avg_px = float(fill["avgPx"])
                total_sz = float(fill["totalSz"])
                notional = avg_px * total_sz
                fees = notional * (settings.taker_fee_pct / 100)
                return OrderResult(
                    success=True,
                    order_id=fill.get("oid"),
                    filled_price=avg_px,
                    quantity=total_sz,
                    fees=round(fees, 6),
                    fill_type="taker",
                    message=f"Market filled: {side} {total_sz} {coin} @ {avg_px:.4f}",
                )

            if "resting" in status:
                # Market order shouldn't rest, but handle gracefully
                return OrderResult(
                    success=False,
                    message=f"Market order is resting (unexpected): {status}",
                )

            if "error" in status:
                return OrderResult(success=False, message=status["error"])

            return OrderResult(
                success=False, message=f"Unexpected order status: {status}"
            )

        except Exception as e:
            logger.exception("Failed to parse order response")
            return OrderResult(success=False, message=f"Parse error: {e}")

    async def get_balance(self) -> float:
        """Get account equity from Hyperliquid."""
        try:
            _, info = self._get_clients()
            address = settings.hl_api_key
            state = await asyncio.to_thread(info.user_state, address)
            return float(state["marginSummary"]["accountValue"])
        except Exception as e:
            logger.exception("Failed to get balance")
            return 0.0

    async def get_current_price(self, symbol: str) -> Optional[float]:
        return await market_data.get_mid_price(symbol)
