"use client";

import { useEffect, useState } from "react";
import { formatPrice } from "@/lib/utils";

interface TickerItem {
  symbol: string;
  price: number;
}

export function MarketTicker() {
  const [tickers, setTickers] = useState<TickerItem[]>([]);

  useEffect(() => {
    const topSymbols = ["BTC", "ETH", "SOL", "DOGE", "ARB", "OP", "AVAX", "SUI", "WIF", "PEPE", "LINK", "AAVE"];

    async function fetchPrices() {
      try {
        const res = await fetch("https://api.hyperliquid.xyz/info", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "allMids" }),
        });
        const data = await res.json();
        const items: TickerItem[] = topSymbols
          .filter((s) => data[s])
          .map((s) => ({ symbol: s, price: parseFloat(data[s]) }));
        setTickers(items);
      } catch {
        // Fallback empty
      }
    }

    fetchPrices();
    const interval = setInterval(fetchPrices, 15000);
    return () => clearInterval(interval);
  }, []);

  if (tickers.length === 0) return null;

  return (
    <div className="relative overflow-hidden rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5">
      <div className="flex items-center gap-8 overflow-x-auto scrollbar-hide">
        {tickers.map((t) => (
          <div
            key={t.symbol}
            className="flex items-center gap-2 text-xs whitespace-nowrap"
          >
            <span className="font-semibold text-white/60">{t.symbol}</span>
            <span className="font-mono text-white/30">${formatPrice(t.price)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
