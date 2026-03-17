"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { IChartApi, Time, LogicalRange } from "lightweight-charts";
import { PriceChart } from "./PriceChart";
import { SqueezePanel } from "./SqueezePanel";
import { OhlcBar, getOhlcFromTime } from "./OhlcBar";
import type { CandleData, EnrichedSTPoint, ChartMarker, SqueezePoint } from "@/types";
import { COLORS } from "@/lib/constants";

interface StatusRow {
  label: string;
  value: string;
  color: string;
}

interface ChartContainerProps {
  candles: CandleData[];
  stPoints: EnrichedSTPoint[];
  markers: ChartMarker[];
  squeezeData: SqueezePoint[];
  currentPrice: number | null;
  containerHeight: number;
  statusRows: StatusRow[];
}

const STATUS_PANEL_HEIGHT = 140;
const OHLC_HEIGHT = 44;
const LABEL_HEIGHT = 18;

export function ChartContainer({
  candles,
  stPoints,
  markers,
  squeezeData,
  currentPrice,
  containerHeight,
  statusRows,
}: ChartContainerProps) {
  const [crosshairTime, setCrosshairTime] = useState<Time | null>(null);
  const chartsRef = useRef<(IChartApi | null)[]>([null, null]);
  const syncingRef = useRef(false);

  // Layout: OHLC bar + Price chart + Squeeze label + Squeeze + Status panel
  const available = containerHeight - OHLC_HEIGHT - LABEL_HEIGHT - STATUS_PANEL_HEIGHT;
  const priceHeight = Math.round(available * 0.72);
  const squeezeHeight = available - priceHeight;

  // Time scale sync between price chart and squeeze
  const syncTimeScale = useCallback((sourceIndex: number) => {
    return (range: LogicalRange | null) => {
      if (syncingRef.current || !range) return;
      syncingRef.current = true;
      chartsRef.current.forEach((chart, i) => {
        if (i !== sourceIndex && chart) {
          chart.timeScale().setVisibleLogicalRange(range);
        }
      });
      syncingRef.current = false;
    };
  }, []);

  const handlePriceChartReady = useCallback((chart: IChartApi) => {
    chartsRef.current[0] = chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncTimeScale(0));
    setTimeout(() => {
      chartsRef.current.forEach((c) => c?.timeScale().scrollToRealTime());
      const range = chart.timeScale().getVisibleLogicalRange();
      if (range) {
        chartsRef.current.forEach((c, i) => {
          if (i !== 0 && c) c.timeScale().setVisibleLogicalRange(range);
        });
      }
    }, 150);
  }, [syncTimeScale]);

  const handleSqueezeChartReady = useCallback((chart: IChartApi) => {
    chartsRef.current[1] = chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncTimeScale(1));
    const priceChart = chartsRef.current[0];
    if (priceChart) {
      const range = priceChart.timeScale().getVisibleLogicalRange();
      if (range) chart.timeScale().setVisibleLogicalRange(range);
    }
  }, [syncTimeScale]);

  const handleCrosshairMove = useCallback((time: Time | null) => {
    setCrosshairTime(time);
  }, []);

  const hoveredCandle = useMemo(
    () => getOhlcFromTime(candles, crosshairTime as number | null),
    [candles, crosshairTime],
  );

  const hoveredSupertrend = useMemo(
    () => {
      if (!crosshairTime) return null;
      const t = crosshairTime as number;
      for (let i = stPoints.length - 1; i >= 0; i--) {
        if (stPoints[i].time <= t) return { value: stPoints[i].value, direction: stPoints[i].direction };
      }
      return null;
    },
    [stPoints, crosshairTime],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: `${containerHeight}px`, overflow: "hidden" }}>
      {/* OHLC Info Bar */}
      <OhlcBar
        candle={hoveredCandle}
        currentPrice={currentPrice}
        supertrendValue={hoveredSupertrend?.value ?? null}
        supertrendDirection={hoveredSupertrend?.direction ?? null}
      />

      {/* Price Chart */}
      <PriceChart
        candles={candles}
        stPoints={stPoints}
        markers={markers}
        height={priceHeight}
        onCrosshairMove={handleCrosshairMove}
        onChartReady={handlePriceChartReady}
      />

      {/* Squeeze label */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "1px 10px",
          backgroundColor: "#1e222d",
          borderTop: "1px solid rgba(42,46,57,0.5)",
          height: `${LABEL_HEIGHT}px`,
          minHeight: `${LABEL_HEIGHT}px`,
        }}
      >
        <span style={{ fontSize: "9px", color: "#787b86", fontFamily: "'JetBrains Mono', monospace" }}>
          SQZMOM_LB · BB 20/2 · KC 20/1.5
        </span>
      </div>

      {/* Squeeze Momentum */}
      <SqueezePanel
        data={squeezeData}
        height={squeezeHeight}
        onCrosshairMove={handleCrosshairMove}
        onChartReady={handleSqueezeChartReady}
      />

      {/* Status Table Panel — fixed at bottom */}
      <div
        style={{
          height: `${STATUS_PANEL_HEIGHT}px`,
          minHeight: `${STATUS_PANEL_HEIGHT}px`,
          backgroundColor: "#12131a",
          borderTop: "1px solid rgba(42,46,57,0.6)",
          padding: "8px 12px 6px",
          display: "flex",
          flexDirection: "column",
          gap: "0px",
        }}
      >
        <div style={{
          fontSize: "9px",
          fontWeight: 700,
          color: "#787b86",
          letterSpacing: "0.8px",
          textTransform: "uppercase",
          marginBottom: "6px",
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          MTF Recovery ST + ADX + Squeeze
        </div>
        {statusRows.map((row) => (
          <div
            key={row.label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "3px 0",
              borderBottom: "1px solid rgba(42,46,57,0.25)",
            }}
          >
            <span style={{
              fontSize: "11px",
              color: "#787b86",
              fontFamily: "'JetBrains Mono', monospace",
              fontWeight: 500,
            }}>
              {row.label}
            </span>
            <span style={{
              fontSize: "11px",
              fontWeight: 700,
              color: row.color,
              fontFamily: "'JetBrains Mono', monospace",
            }}>
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
