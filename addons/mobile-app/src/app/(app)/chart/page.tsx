"use client";

import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { useCandles, useCurrentPrice } from "@/hooks/useHyperliquid";
import { calcSupertrend, calcSqueezeMomentum, calcMacdRsi, calcAdx } from "@/lib/indicators";
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
interface StatusData {
  st15m: "BULL" | "BEAR" | null;
  st1h: "BULL" | "BEAR" | null;
  aligned: boolean;
  adxValue: number | null;
  adxRising: boolean;
  squeezeOn: boolean | null;
  signalReady: boolean;
  signalBlockReason: string;
}

function StatusOverlay({ status }: { status: StatusData | null }) {
  if (!status) return null;

  const rows: { label: string; value: string; color: string }[] = [
    {
      label: "15m ST",
      value: status.st15m ?? "—",
      color: status.st15m === "BULL" ? COLORS.bullish : status.st15m === "BEAR" ? COLORS.bearish : COLORS.textSecondary,
    },
    {
      label: "1H ST",
      value: status.st1h ?? "—",
      color: status.st1h === "BULL" ? COLORS.bullish : status.st1h === "BEAR" ? COLORS.bearish : COLORS.textSecondary,
    },
    {
      label: "Aligned",
      value: status.aligned ? "YES" : "NO",
      color: status.aligned ? COLORS.bullish : COLORS.bearish,
    },
    {
      label: "ADX",
      value: status.adxValue !== null ? `${status.adxValue.toFixed(1)} ${status.adxRising ? "RISING" : "falling"}` : "—",
      color: status.adxValue !== null && status.adxValue >= 15 && status.adxRising ? COLORS.bullish : COLORS.textSecondary,
    },
    {
      label: "Squeeze",
      value: status.squeezeOn === null ? "—" : status.squeezeOn ? "ON blocked" : "OFF ok",
      color: status.squeezeOn ? COLORS.bearish : COLORS.bullish,
    },
    {
      label: "Signal",
      value: status.signalReady ? "READY" : `BLOCKED`,
      color: status.signalReady ? COLORS.bullish : COLORS.bearish,
    },
  ];

  return (
    <div
      style={{
        position: "absolute",
        top: "8px",
        left: "8px",
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        gap: "3px",
        padding: "6px 8px",
        borderRadius: "6px",
        backgroundColor: "rgba(10,10,15,0.9)",
        border: `1px solid ${COLORS.border}`,
        backdropFilter: "blur(8px)",
        pointerEvents: "none",
        minWidth: "140px",
      }}
    >
      <div style={{ fontSize: "8px", color: COLORS.textSecondary, fontWeight: 600, letterSpacing: "0.5px", marginBottom: "1px" }}>
        MTF Recovery ST + ADX + SQZ
      </div>
      {rows.map((r) => (
        <div key={r.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "9px", color: COLORS.textSecondary, fontFamily: "'JetBrains Mono', monospace" }}>{r.label}</span>
          <span style={{ fontSize: "9px", fontWeight: 700, color: r.color, fontFamily: "'JetBrains Mono', monospace" }}>{r.value}</span>
        </div>
      ))}
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
  const { data: candles1h } = useCandles(activeCoin, "1h", 14);
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

  // Full status for overlay
  const statusData = useMemo((): StatusData | null => {
    if (!candles || candles.length < 50) return null;

    // 15m ST direction (last closed candle)
    const st15m = indicators?.supertrend?.points;
    const last15m = st15m && st15m.length > 1 ? st15m[st15m.length - 2] : null;
    const dir15m = last15m ? (last15m.direction === "bullish" ? "BULL" as const : "BEAR" as const) : null;

    // 1H ST direction
    let dir1h: "BULL" | "BEAR" | null = null;
    if (candles1h && candles1h.length > 20) {
      const st1hResult = calcSupertrend(candles1h, { atrPeriod: 10, multiplier: 4.0, source: "close" });
      const last1h = st1hResult.points.length > 1 ? st1hResult.points[st1hResult.points.length - 2] : null;
      dir1h = last1h ? (last1h.direction === "bullish" ? "BULL" : "BEAR") : null;
    }

    const aligned = dir15m !== null && dir1h !== null && dir15m === dir1h;

    // ADX
    const adxResult = calcAdx(candles, 14);
    const adxValue = adxResult?.adx ?? null;
    const adxRising = adxResult?.rising ?? false;
    const adxPass = adxValue !== null && adxValue >= 15 && adxRising;

    // Squeeze (last closed candle)
    const sqzPoints = indicators?.squeeze;
    const lastSqz = sqzPoints && sqzPoints.length > 1 ? sqzPoints[sqzPoints.length - 2] : null;
    const squeezeOn = lastSqz?.squeezeOn ?? null;
    const sqzPass = squeezeOn === false;

    const signalReady = aligned && adxPass && sqzPass;
    let blockReason = "";
    if (!aligned) blockReason = "timeframes disagree";
    else if (!adxPass) blockReason = adxValue !== null && adxValue < 15 ? "ADX below 15" : "ADX falling";
    else if (!sqzPass) blockReason = "squeeze on";

    return { st15m: dir15m, st1h: dir1h, aligned, adxValue, adxRising, squeezeOn, signalReady, signalBlockReason: blockReason };
  }, [candles, candles1h, indicators]);

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
          <StatusOverlay status={statusData} />
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
