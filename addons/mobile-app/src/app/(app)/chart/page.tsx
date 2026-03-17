"use client";

import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { useCandles, useCurrentPrice } from "@/hooks/useHyperliquid";
import { calcSupertrend, calcSqueezeMomentum, calcMacdRsi } from "@/lib/indicators";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useLivePositions } from "@/hooks/useApi";
import { SkeletonChart } from "@/components/ui/Skeleton";
import { ASSET_COLORS, COLORS, TIMEFRAMES } from "@/lib/constants";
import type { HLPosition, SupertrendPoint } from "@/types";

const ChartContainer = dynamic(
  () => import("@/components/chart/ChartContainer").then((m) => ({ default: m.ChartContainer })),
  { ssr: false, loading: () => <ChartLoadingSkeleton /> },
);

const HEADER_HEIGHT = 96; // asset selector + timeframe bar (safe area handled by parent layout)

/* ── Asset Selector ── */
function AssetSelector({
  active,
  onChange,
  positions,
}: {
  active: string;
  onChange: (coin: string) => void;
  positions: HLPosition[];
}) {
  const coins = ["BTC", "ETH", "SOL"];
  return (
    <div style={{ display: "flex", gap: "8px", padding: "8px 12px 4px" }}>
      {coins.map((coin) => {
        const isActive = coin === active;
        const color = ASSET_COLORS[coin] ?? "#888";
        const pos = positions.find((p) => p.symbol === coin);
        const posColor = pos ? (pos.side === "long" ? COLORS.bullish : COLORS.bearish) : undefined;

        return (
          <button
            key={coin}
            onClick={() => onChange(coin)}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
              padding: "8px 0",
              borderRadius: "10px",
              border: isActive ? `1.5px solid ${color}` : "1.5px solid transparent",
              backgroundColor: isActive ? `${color}15` : "rgba(255,255,255,0.03)",
              transition: "all 0.2s",
              cursor: "pointer",
              position: "relative",
            }}
          >
            {posColor && (
              <span
                style={{
                  position: "absolute",
                  top: "4px",
                  right: "6px",
                  width: "5px",
                  height: "5px",
                  borderRadius: "50%",
                  backgroundColor: posColor,
                  boxShadow: `0 0 4px ${posColor}`,
                }}
              />
            )}
            <span
              style={{
                fontSize: "13px",
                fontWeight: isActive ? 700 : 500,
                color: isActive ? color : COLORS.textSecondary,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              {coin}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ── Timeframe Selector ── */
function TimeframeSelector({
  active,
  onChange,
}: {
  active: string;
  onChange: (tf: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: "4px", padding: "4px 12px 6px" }}>
      {TIMEFRAMES.map((tf) => {
        const isActive = tf === active;
        return (
          <button
            key={tf}
            onClick={() => onChange(tf)}
            style={{
              flex: 1,
              padding: "4px 0",
              borderRadius: "6px",
              border: "none",
              backgroundColor: isActive ? "rgba(41,98,255,0.2)" : "transparent",
              color: isActive ? "#2962ff" : COLORS.textSecondary,
              fontSize: "11px",
              fontWeight: isActive ? 600 : 400,
              fontFamily: "'JetBrains Mono', monospace",
              cursor: "pointer",
              transition: "all 0.15s",
            }}
          >
            {tf}
          </button>
        );
      })}
    </div>
  );
}

/* ── Position Info Bar ── */
function PositionBar({ position, coin }: { position: HLPosition | undefined; coin: string }) {
  const color = ASSET_COLORS[coin] ?? "#888";

  if (!position) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "6px 12px",
          borderTop: `1px solid ${COLORS.border}`,
          borderBottom: `1px solid ${COLORS.border}`,
          backgroundColor: "rgba(255,255,255,0.01)",
        }}
      >
        <span style={{ fontSize: "11px", color: COLORS.textSecondary }}>
          No position — watching for signals
        </span>
      </div>
    );
  }

  const isLong = position.side === "long";
  const pnl = position.unrealized_pnl;
  const pnlPct = position.entry_price > 0
    ? ((position.mark_price - position.entry_price) / position.entry_price * 100 * (isLong ? 1 : -1))
    : 0;
  const sideColor = isLong ? COLORS.bullish : COLORS.bearish;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "6px 12px",
        borderTop: `1px solid ${COLORS.border}`,
        borderBottom: `1px solid ${COLORS.border}`,
        backgroundColor: `${sideColor}08`,
      }}
    >
      <span
        style={{
          fontSize: "10px",
          fontWeight: 700,
          color: "#fff",
          backgroundColor: sideColor,
          padding: "2px 6px",
          borderRadius: "4px",
          letterSpacing: "0.5px",
        }}
      >
        {position.side.toUpperCase()}
      </span>
      <span style={{ fontSize: "11px", color: COLORS.textSecondary, fontFamily: "'JetBrains Mono', monospace" }}>
        {position.entry_price.toLocaleString("en", { maximumFractionDigits: 2 })}
        {" → "}
        {position.mark_price.toLocaleString("en", { maximumFractionDigits: 2 })}
      </span>
      <span
        style={{
          marginLeft: "auto",
          fontSize: "12px",
          fontWeight: 600,
          color: pnl >= 0 ? COLORS.bullish : COLORS.bearish,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(1)}%)
      </span>
    </div>
  );
}

/* ── Status Overlay ── */
function StatusOverlay({
  supertrendPoints,
  coin,
}: {
  supertrendPoints: SupertrendPoint[];
  coin: string;
}) {
  // Get last closed candle's direction
  const lastSt = supertrendPoints.length > 1 ? supertrendPoints[supertrendPoints.length - 2] : null;
  if (!lastSt) return null;

  const isBullish = lastSt.direction === "bullish";

  return (
    <div
      style={{
        position: "absolute",
        top: "8px",
        left: "8px",
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        gap: "2px",
        padding: "6px 8px",
        borderRadius: "6px",
        backgroundColor: "rgba(10,10,15,0.85)",
        border: `1px solid ${COLORS.border}`,
        backdropFilter: "blur(8px)",
        pointerEvents: "none",
      }}
    >
      <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
        <span style={{ fontSize: "9px", color: COLORS.textSecondary, width: "32px" }}>15m ST</span>
        <span
          style={{
            fontSize: "9px",
            fontWeight: 700,
            color: isBullish ? COLORS.bullish : COLORS.bearish,
          }}
        >
          {isBullish ? "BULL" : "BEAR"}
        </span>
      </div>
    </div>
  );
}

/* ── Loading & Error ── */
function ChartLoadingSkeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ flex: 1 }}>
        <SkeletonChart className="h-full rounded-none border-0" />
      </div>
    </div>
  );
}

function ChartError({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "16px",
        padding: "32px",
        height: "100%",
      }}
    >
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#ff1744" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <p style={{ fontSize: "14px", color: COLORS.textPrimary, textAlign: "center" }}>
        Failed to load chart data
      </p>
      <p style={{ fontSize: "12px", color: COLORS.textSecondary, textAlign: "center" }}>
        {error}
      </p>
      <button
        onClick={onRetry}
        style={{
          padding: "10px 24px",
          borderRadius: "8px",
          border: "none",
          backgroundColor: "#2962ff",
          color: "#fff",
          fontSize: "14px",
          fontWeight: 500,
          cursor: "pointer",
        }}
      >
        Retry
      </button>
    </div>
  );
}

/* ── Main Chart Page ── */
export default function ChartPage() {
  const [activeCoin, setActiveCoin] = useState("BTC");
  const [timeframe, setTimeframe] = useState("15m");
  const tfLower = timeframe.toLowerCase();

  const daysMap: Record<string, number> = { "5m": 3, "15m": 7, "1h": 14, "4h": 30, "1d": 90 };
  const days = daysMap[tfLower] ?? 7;

  const { data: candles, error: candleError, mutate: retryCandles } = useCandles(activeCoin, tfLower, days);
  const { data: currentPrice } = useCurrentPrice(activeCoin);
  const { data: positions } = useLivePositions();
  const { connected } = useWebSocket();
  const [chartHeight, setChartHeight] = useState(0);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const activePosition = positions?.find((p) => p.symbol === activeCoin);

  const posBarHeight = 30;

  useEffect(() => {
    const measure = () => {
      if (wrapperRef.current) {
        const rect = wrapperRef.current.getBoundingClientRect();
        setChartHeight(Math.floor(rect.height) - HEADER_HEIGHT - posBarHeight);
      }
    };
    const timer = setTimeout(measure, 100);
    window.addEventListener("resize", measure);
    window.addEventListener("orientationchange", () => setTimeout(measure, 300));
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", measure);
    };
  }, []);

  const indicators = useMemo(() => {
    if (!candles || candles.length === 0) return null;
    return {
      supertrend: calcSupertrend(candles),
      squeeze: calcSqueezeMomentum(candles),
      macdRsi: calcMacdRsi(candles),
    };
  }, [candles]);

  const handleCoinChange = useCallback((coin: string) => {
    setActiveCoin(coin);
  }, []);

  const handleTimeframeChange = useCallback((tf: string) => {
    setTimeframe(tf);
  }, []);

  return (
    <div
      ref={wrapperRef}
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        backgroundColor: COLORS.bgPrimary,
      }}
    >
      {/* Asset Selector */}
      <AssetSelector
        active={activeCoin}
        onChange={handleCoinChange}
        positions={positions ?? []}
      />

      {/* Timeframe Selector */}
      <TimeframeSelector active={timeframe} onChange={handleTimeframeChange} />

      {/* Position Bar */}
      <PositionBar position={activePosition} coin={activeCoin} />

      {/* Chart */}
      {candleError ? (
        <ChartError
          error={candleError instanceof Error ? candleError.message : "Connection error"}
          onRetry={() => retryCandles()}
        />
      ) : !candles || !indicators || chartHeight <= 0 ? (
        <ChartLoadingSkeleton />
      ) : (
        <div style={{ position: "relative", flex: 1 }}>
          <StatusOverlay supertrendPoints={indicators.supertrend.points} coin={activeCoin} />
          <ChartContainer
            candles={candles}
            supertrendPoints={indicators.supertrend.points}
            supertrendSignals={indicators.supertrend.signals}
            squeezeData={indicators.squeeze}
            macdRsiData={indicators.macdRsi}
            currentPrice={currentPrice ?? null}
            containerHeight={chartHeight}
          />
        </div>
      )}
    </div>
  );
}
