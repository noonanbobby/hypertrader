"use client";

import { memo } from "react";
import type { CandleData, SupertrendPoint } from "@/types";
import { formatPrice } from "@/lib/format";

interface OhlcBarProps {
  candle: CandleData | null;
  currentPrice: number | null;
  supertrendValue: number | null;
  supertrendDirection: "bullish" | "bearish" | null;
}

export const OhlcBar = memo(function OhlcBar({
  candle,
  currentPrice,
  supertrendValue,
  supertrendDirection,
}: OhlcBarProps) {
  const isBullish = candle ? candle.close >= candle.open : true;
  const priceColor = isBullish ? "#26a69a" : "#ef5350";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "2px",
        padding: "6px 10px",
        backgroundColor: "#1e222d",
        borderBottom: "1px solid rgba(42,46,57,0.5)",
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {/* Row 1: Symbol + price */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ fontSize: "13px", fontWeight: 600, color: "#d1d4dc" }}>BTC</span>
        <span style={{ fontSize: "10px", color: "#787b86" }}>15m</span>
        {currentPrice !== null && (
          <span style={{ fontSize: "13px", fontWeight: 600, color: priceColor, marginLeft: "auto" }}>
            {formatPrice(currentPrice)}
          </span>
        )}
      </div>

      {/* Row 2: OHLC values */}
      {candle && (
        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
          <OhlcValue label="O" value={candle.open} color={priceColor} />
          <OhlcValue label="H" value={candle.high} color={priceColor} />
          <OhlcValue label="L" value={candle.low} color={priceColor} />
          <OhlcValue label="C" value={candle.close} color={priceColor} />
          {supertrendValue !== null && supertrendDirection !== null && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "2px",
                fontSize: "10px",
                color: supertrendDirection === "bullish" ? "#26a69a" : "#ef5350",
                marginLeft: "auto",
              }}
            >
              ST {formatPrice(supertrendValue)}
              <span style={{ fontSize: "8px" }}>
                {supertrendDirection === "bullish" ? "▲" : "▼"}
              </span>
            </span>
          )}
        </div>
      )}
    </div>
  );
});

function OhlcValue({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "2px", fontSize: "10px" }}>
      <span style={{ color: "#787b86" }}>{label}:</span>
      <span style={{ color }}>{formatPrice(value)}</span>
    </span>
  );
}

export function getOhlcFromTime(
  candles: CandleData[],
  time: number | null,
): CandleData | null {
  if (time === null || candles.length === 0) {
    return candles[candles.length - 1] ?? null;
  }
  const found = candles.find((c) => c.time === time);
  return found ?? candles[candles.length - 1] ?? null;
}

export function getSupertrendAtTime(
  points: SupertrendPoint[],
  time: number | null,
): { value: number; direction: "bullish" | "bearish" } | null {
  if (points.length === 0) return null;
  if (time === null) {
    const last = points[points.length - 1];
    return { value: last.value, direction: last.direction };
  }
  const found = points.find((p) => p.time === time);
  if (found) return { value: found.value, direction: found.direction };
  const last = points[points.length - 1];
  return { value: last.value, direction: last.direction };
}
