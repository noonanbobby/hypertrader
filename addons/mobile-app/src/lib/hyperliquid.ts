import { HL_API_URL } from "./constants";
import type { CandleData } from "@/types";

interface HLCandleRaw {
  t: number;
  T: number;
  s: string;
  i: string;
  o: string;
  c: string;
  h: string;
  l: string;
  v: string;
  n: number;
}

export async function fetchCandles(
  coin: string,
  interval: string,
  startTime: number,
  endTime: number,
): Promise<CandleData[]> {
  const res = await fetch(HL_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type: "candleSnapshot",
      req: { coin, interval, startTime, endTime },
    }),
  });

  if (!res.ok) {
    throw new Error(`Hyperliquid API error: ${res.status}`);
  }

  const raw: HLCandleRaw[] = await res.json();

  return raw.map((c) => ({
    time: Math.floor(c.t / 1000) as number,
    open: parseFloat(c.o),
    high: parseFloat(c.h),
    low: parseFloat(c.l),
    close: parseFloat(c.c),
    volume: parseFloat(c.v),
  }));
}

export async function fetchAllMids(): Promise<Record<string, string>> {
  const res = await fetch(HL_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "allMids" }),
  });

  if (!res.ok) {
    throw new Error(`Hyperliquid API error: ${res.status}`);
  }

  return res.json();
}

export async function fetchCurrentPrice(coin: string): Promise<number> {
  const mids = await fetchAllMids();
  const price = mids[coin];
  if (!price) {
    throw new Error(`Price not available for ${coin}`);
  }
  return parseFloat(price);
}
