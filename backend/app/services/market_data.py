import httpx
from typing import Optional


HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


class MarketDataService:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._price_cache: dict[str, float] = {}
        self._sz_decimals: dict[str, int] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def get_all_mids(self) -> dict[str, float]:
        """Fetch all mid prices from Hyperliquid."""
        client = await self._get_client()
        try:
            response = await client.post(
                HYPERLIQUID_INFO_URL,
                json={"type": "allMids"},
            )
            response.raise_for_status()
            data = response.json()
            # data is a dict of symbol -> mid price string
            self._price_cache = {k: float(v) for k, v in data.items()}
            return self._price_cache
        except Exception:
            return self._price_cache

    async def get_mid_price(self, symbol: str) -> Optional[float]:
        """Get current mid price for a symbol."""
        clean_symbol = self.normalize_coin(symbol)

        # Try cache first, then fetch
        if clean_symbol not in self._price_cache:
            await self.get_all_mids()

        return self._price_cache.get(clean_symbol)

    async def get_sz_decimals(self, coin: str) -> int:
        """Get szDecimals for a coin, fetching and caching from meta endpoint."""
        if coin in self._sz_decimals:
            return self._sz_decimals[coin]

        meta = await self.get_meta()
        if meta and "universe" in meta:
            for asset in meta["universe"]:
                self._sz_decimals[asset["name"]] = asset.get("szDecimals", 5)

        return self._sz_decimals.get(coin, 5)

    def normalize_coin(self, symbol: str) -> str:
        """Normalize symbol to Hyperliquid coin format.

        Handles TradingView formats: BTCUSDT.P, ETHUSDT.P, SOLUSDT.P
        and standard formats: BTCUSDT, BTCUSDC, BTC-PERP, BTC/USD, BTC
        """
        coin = symbol.upper().strip()
        # TradingView perpetual suffix (e.g. BTCUSDT.P)
        if coin.endswith(".P"):
            coin = coin[:-2]
        coin = coin.replace("-PERP", "").replace("/USD", "")
        for suffix in ("USDC", "USDT", "USD", "PERP"):
            if coin.endswith(suffix) and len(coin) > len(suffix):
                coin = coin[: -len(suffix)]
                break
        return coin

    async def get_best_bid_ask(self, symbol: str) -> tuple[Optional[float], Optional[float]]:
        """Get best bid and ask from L2 order book."""
        coin = self.normalize_coin(symbol)
        client = await self._get_client()
        try:
            response = await client.post(
                HYPERLIQUID_INFO_URL,
                json={"type": "l2Book", "coin": coin},
            )
            response.raise_for_status()
            data = response.json()
            levels = data.get("levels", [[], []])
            bids = levels[0] if len(levels) > 0 else []
            asks = levels[1] if len(levels) > 1 else []
            best_bid = float(bids[0]["px"]) if bids else None
            best_ask = float(asks[0]["px"]) if asks else None
            return best_bid, best_ask
        except Exception:
            return None, None

    async def get_meta(self) -> dict:
        """Fetch exchange metadata (available assets, etc)."""
        client = await self._get_client()
        try:
            response = await client.post(
                HYPERLIQUID_INFO_URL,
                json={"type": "meta"},
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return {}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


market_data = MarketDataService()
