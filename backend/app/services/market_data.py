import httpx
from typing import Optional


HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


class MarketDataService:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._price_cache: dict[str, float] = {}

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
        # Normalize symbol (remove -PERP suffix if present)
        clean_symbol = symbol.replace("-PERP", "").replace("/USD", "").upper()

        # Try cache first, then fetch
        if clean_symbol not in self._price_cache:
            await self.get_all_mids()

        return self._price_cache.get(clean_symbol)

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
