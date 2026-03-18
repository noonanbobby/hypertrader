"use client";

import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import dynamicImport from "next/dynamic";
import { useCandles, useCurrentPrice } from "@/hooks/useHyperliquid";
import { calcSupertrend, calcSqueezeMomentum, calcAdx } from "@/lib/indicators";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useLivePositions, useLiveFills } from "@/hooks/useApi";
import { SkeletonChart } from "@/components/ui/Skeleton";
import { ASSET_COLORS, COLORS, TIMEFRAMES } from "@/lib/constants";
import type { HLPosition, EnrichedSTPoint, ChartMarker } from "@/types";

const ChartContainer = dynamicImport(
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

/* ── Status Data ── */
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
  const { data: fills } = useLiveFills();
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

  const squeeze15m = useMemo(() => {
    if (!candles || candles.length === 0) return null;
    return calcSqueezeMomentum(candles);
  }, [candles]);

  // Compute enriched ST points, markers, and status data
  const chartData = useMemo(() => {
    if (!candles || candles.length < 50) return null;

    // 15m Supertrend
    const st15mResult = calcSupertrend(candles);
    const st15mPoints = st15mResult.points;

    // 1H Supertrend — compute and align to 15m bars
    let htfDirByTime: Map<number, "bullish" | "bearish"> = new Map();
    if (candles1h && candles1h.length > 20) {
      const st1hResult = calcSupertrend(candles1h, { atrPeriod: 10, multiplier: 4.0, source: "close" });
      // Build time→direction map for 1H, then for each 15m bar find the most recent 1H direction
      const htfPoints = st1hResult.points;
      let hIdx = 0;
      for (const c of candles) {
        while (hIdx < htfPoints.length - 1 && htfPoints[hIdx + 1].time <= c.time) hIdx++;
        if (hIdx < htfPoints.length) {
          htfDirByTime.set(c.time, htfPoints[hIdx].direction);
        }
      }
    }

    // ADX per bar (we just need the latest values for status, but for line coloring we need per-bar)
    const adxResult = calcAdx(candles, 14);
    const adxValue = adxResult?.adx ?? null;
    const adxRising = adxResult?.rising ?? false;

    // Squeeze per bar — use the squeeze momentum data
    const sqzPoints = squeeze15m;

    // Build EnrichedSTPoint[] — one per bar where ST is defined
    const enriched: EnrichedSTPoint[] = [];
    const allMarkers: ChartMarker[] = [];

    // Create a time→squeeze lookup
    const sqzByTime = new Map<number, boolean>();
    if (sqzPoints) {
      for (const sp of sqzPoints) sqzByTime.set(sp.time, sp.squeezeOn);
    }

    // For ADX, we only have the latest value — for per-bar coloring, compute a simplified per-bar ADX
    // Actually the calcAdx returns only the final value. For line coloring we need to know per-bar.
    // Simplification: use the global ADX status for the last ~200 bars (the visible range).
    // This is acceptable because ADX changes slowly.

    for (let i = 0; i < st15mPoints.length; i++) {
      const pt = st15mPoints[i];
      const htfDir = htfDirByTime.get(pt.time) ?? null;
      const sqzOn = sqzByTime.get(pt.time) ?? true;
      const isBull = pt.direction === "bullish";

      // Filter check for this bar's line color
      const htfAgrees = htfDir !== null && ((isBull && htfDir === "bullish") || (!isBull && htfDir === "bearish"));
      const adxPass = adxValue !== null && adxValue >= 15 && adxRising;
      const sqzPass = !sqzOn;
      const allFiltersPass = htfAgrees && adxPass && sqzPass;

      // Recovery active: we can't easily detect isAtLoss from the frontend without the full Recovery ST state.
      // Use a heuristic: if the band is moving toward price (tightening), recovery is active.
      const recoveryActive = false; // Simplified — would need full Recovery ST internals

      let lineColor: EnrichedSTPoint["lineColor"];
      if (allFiltersPass) {
        lineColor = isBull ? "green" : "red";
      } else {
        lineColor = "gray";
      }

      enriched.push({
        time: pt.time,
        value: pt.value,
        direction: pt.direction,
        lineColor,
        lineStyle: recoveryActive ? "dotted" : "solid",
        htfDir: htfDir,
        adxPass,
        squeezeOff: sqzPass,
        recoveryActive,
      });

      // Markers — direction changes
      if (i > 0 && st15mPoints[i - 1].direction !== pt.direction) {
        const flipBull = pt.direction === "bullish";

        // Unfiltered flip markers (always shown, faded)
        allMarkers.push({
          time: pt.time,
          type: flipBull ? "unfilteredBull" : "unfilteredBear",
          price: flipBull ? candles.find((c) => c.time === pt.time)?.low ?? pt.value : candles.find((c) => c.time === pt.time)?.high ?? pt.value,
          label: "",
        });

        if (allFiltersPass) {
          // Full signal — Buy or Sell label
          allMarkers.push({
            time: pt.time,
            type: flipBull ? "buy" : "sell",
            price: flipBull ? candles.find((c) => c.time === pt.time)?.low ?? pt.value : candles.find((c) => c.time === pt.time)?.high ?? pt.value,
            label: flipBull ? "Buy" : "Sell",
          });
        } else {
          // Unfiltered flip = Strategy B exit point (yellow X)
          allMarkers.push({
            time: pt.time,
            type: "exit",
            price: candles.find((c) => c.time === pt.time)?.high ?? pt.value,
            label: "X",
          });
        }
      }
    }

    // Execution markers from fills
    const coinFills = (fills ?? []).filter((f) => f.symbol === activeCoin);
    for (const fill of coinFills) {
      // Convert fill time (epoch ms) to candle time (epoch seconds)
      const fillTimeSec = Math.floor(Number(fill.time) / 1000);
      // Find nearest candle
      let nearestTime = 0;
      let minDist = Infinity;
      for (const c of candles) {
        const dist = Math.abs(c.time - fillTimeSec);
        if (dist < minDist) { minDist = dist; nearestTime = c.time; }
      }
      if (nearestTime > 0 && minDist < 900) { // within 15 min
        const isBuy = fill.side === "buy" || fill.side === "B";
        allMarkers.push({
          time: nearestTime,
          type: isBuy ? "execBuy" : "execSell",
          price: fill.price,
          label: isBuy ? "B" : "S",
        });
      }
    }

    // Status data for the table
    const lastST = st15mPoints.length > 1 ? st15mPoints[st15mPoints.length - 2] : null;
    const dir15m = lastST ? (lastST.direction === "bullish" ? "BULL" as const : "BEAR" as const) : null;
    const lastHTF = lastST ? (htfDirByTime.get(lastST.time) ?? null) : null;
    const dir1h = lastHTF === "bullish" ? "BULL" as const : lastHTF === "bearish" ? "BEAR" as const : null;
    const aligned = dir15m !== null && dir1h !== null && dir15m === dir1h;
    const adxPassFinal = adxValue !== null && adxValue >= 15 && adxRising;
    const lastSqz = sqzPoints && sqzPoints.length > 1 ? sqzPoints[sqzPoints.length - 2] : null;
    const squeezeOn = lastSqz?.squeezeOn ?? null;
    const sqzPassFinal = squeezeOn === false;
    const signalReady = aligned && adxPassFinal && sqzPassFinal;
    let blockReason = "";
    if (!aligned) blockReason = "timeframes disagree";
    else if (!adxPassFinal) blockReason = adxValue !== null && adxValue < 15 ? "ADX below 15" : "ADX falling";
    else if (!sqzPassFinal) blockReason = "squeeze on";

    const status: StatusData = { st15m: dir15m, st1h: dir1h, aligned, adxValue, adxRising, squeezeOn, signalReady, signalBlockReason: blockReason };

    return { enriched, markers: allMarkers, squeeze: squeeze15m ?? [], status };
  }, [candles, candles1h, squeeze15m, fills, activeCoin]);

  const statusRows = useMemo(() => {
    const s = chartData?.status;
    if (!s) return [];
    return [
      { label: "15m ST", value: s.st15m ?? "—", color: s.st15m === "BULL" ? COLORS.bullish : s.st15m === "BEAR" ? COLORS.bearish : COLORS.textSecondary },
      { label: "1H ST", value: s.st1h ?? "—", color: s.st1h === "BULL" ? COLORS.bullish : s.st1h === "BEAR" ? COLORS.bearish : COLORS.textSecondary },
      { label: "Aligned", value: s.aligned ? "YES" : "NO", color: s.aligned ? COLORS.bullish : "#ff9800" },
      { label: "ADX(14)", value: s.adxValue !== null ? `${s.adxValue.toFixed(1)} ${s.adxRising ? "RISING" : "falling"}` : "—", color: s.adxValue !== null && s.adxValue >= 15 && s.adxRising ? COLORS.bullish : COLORS.textSecondary },
      { label: "Squeeze", value: s.squeezeOn === null ? "—" : s.squeezeOn ? "ON blocked" : "OFF ok", color: s.squeezeOn ? "#ff9800" : COLORS.bullish },
      { label: "Recovery", value: s.st15m !== null ? "ACTIVE" : "standby", color: s.st15m !== null ? "#ff9800" : COLORS.textSecondary },
      { label: "Signal", value: s.signalReady ? "READY" : `BLOCKED: ${s.signalBlockReason}`, color: s.signalReady ? COLORS.bullish : COLORS.bearish },
    ];
  }, [chartData]);

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
      ) : !candles || !chartData || chartHeight <= 0 ? (
        <ChartLoadingSkeleton />
      ) : (
        <div style={{ flex: 1 }}>
          <ChartContainer
            candles={candles}
            stPoints={chartData.enriched}
            markers={chartData.markers}
            squeezeData={chartData.squeeze}
            currentPrice={currentPrice ?? null}
            containerHeight={chartHeight}
            statusRows={statusRows}
          />
        </div>
      )}
    </div>
  );
}
