"use client";

import useSWR from "swr";
import { fetchCandles, fetchCurrentPrice } from "@/lib/hyperliquid";
import { REFRESH_INTERVALS } from "@/lib/constants";

export function useCandles(coin: string, interval: string, days: number = 7) {
  const key = `candles-${coin}-${interval}-${days}`;
  return useSWR(
    key,
    async () => {
      const now = Date.now();
      const startTime = now - days * 24 * 60 * 60 * 1000;
      return fetchCandles(coin, interval, startTime, now);
    },
    {
      refreshInterval: REFRESH_INTERVALS.price,
      revalidateOnFocus: true,
      errorRetryCount: 3,
      dedupingInterval: 3000,
    },
  );
}

export function useCurrentPrice(coin: string) {
  return useSWR(
    `price-${coin}`,
    () => fetchCurrentPrice(coin),
    {
      refreshInterval: REFRESH_INTERVALS.price,
      revalidateOnFocus: true,
      errorRetryCount: 3,
      dedupingInterval: 2000,
    },
  );
}
