"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { IChartApi, Time, LogicalRange } from "lightweight-charts";
import { PriceChart } from "./PriceChart";
import { SqueezePanel } from "./SqueezePanel";
import { MacdRsiPanel } from "./MacdRsiPanel";
import { OhlcBar, getOhlcFromTime, getSupertrendAtTime } from "./OhlcBar";
import type { CandleData, SupertrendPoint, SupertrendSignal, SqueezePoint, MacdRsiPoint } from "@/types";

interface ChartContainerProps {
  candles: CandleData[];
  supertrendPoints: SupertrendPoint[];
  supertrendSignals: SupertrendSignal[];
  squeezeData: SqueezePoint[];
  macdRsiData: MacdRsiPoint[];
  currentPrice: number | null;
  containerHeight: number;
}

export function ChartContainer({
  candles,
  supertrendPoints,
  supertrendSignals,
  squeezeData,
  macdRsiData,
  currentPrice,
  containerHeight,
}: ChartContainerProps) {
  const [crosshairTime, setCrosshairTime] = useState<Time | null>(null);
  const chartsRef = useRef<(IChartApi | null)[]>([null, null, null]);
  const syncingRef = useRef(false);

  // Panel heights: OHLC bar ~44px, indicator labels ~20px each, rest splits 57/20/23
  const ohlcHeight = 44;
  const labelHeight = 20;
  const available = containerHeight - ohlcHeight - labelHeight * 2;
  const priceHeight = Math.round(available * 0.57);
  const squeezeHeight = Math.round(available * 0.20);
  const macdHeight = available - priceHeight - squeezeHeight;

  // Time scale sync — when one chart scrolls/zooms, sync the others
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

  const scrollAllToRealTime = useCallback(() => {
    chartsRef.current.forEach((chart) => {
      if (chart) chart.timeScale().scrollToRealTime();
    });
  }, []);

  const handlePriceChartReady = useCallback((chart: IChartApi) => {
    chartsRef.current[0] = chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncTimeScale(0));
    // Scroll to latest bar after a short delay for data to settle
    setTimeout(() => chart.timeScale().scrollToRealTime(), 100);
  }, [syncTimeScale]);

  const handleSqueezeChartReady = useCallback((chart: IChartApi) => {
    chartsRef.current[1] = chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncTimeScale(1));
  }, [syncTimeScale]);

  const handleMacdChartReady = useCallback((chart: IChartApi) => {
    chartsRef.current[2] = chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncTimeScale(2));
  }, [syncTimeScale]);

  const handleCrosshairMove = useCallback((time: Time | null) => {
    setCrosshairTime(time);
  }, []);

  const hoveredCandle = useMemo(
    () => getOhlcFromTime(candles, crosshairTime as number | null),
    [candles, crosshairTime],
  );

  const hoveredSupertrend = useMemo(
    () => getSupertrendAtTime(supertrendPoints, crosshairTime as number | null),
    [supertrendPoints, crosshairTime],
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

      {/* Price Chart — 57% */}
      <PriceChart
        candles={candles}
        supertrendPoints={supertrendPoints}
        supertrendSignals={supertrendSignals}
        height={priceHeight}
        onCrosshairMove={handleCrosshairMove}
        onChartReady={handlePriceChartReady}
      />

      {/* Squeeze label */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "2px 10px",
          backgroundColor: "#1e222d",
          borderTop: "1px solid rgba(42,46,57,0.5)",
          height: `${labelHeight}px`,
          minHeight: `${labelHeight}px`,
        }}
      >
        <span style={{ fontSize: "9px", color: "#787b86", fontFamily: "'JetBrains Mono', monospace" }}>
          SQZMOM_LB · BB 20/2 · KC 20/1.5
        </span>
      </div>

      {/* Squeeze Momentum — 20% */}
      <SqueezePanel
        data={squeezeData}
        height={squeezeHeight}
        onCrosshairMove={handleCrosshairMove}
        onChartReady={handleSqueezeChartReady}
      />

      {/* MACD+RSI label */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "2px 10px",
          backgroundColor: "#1e222d",
          borderTop: "1px solid rgba(42,46,57,0.5)",
          height: `${labelHeight}px`,
          minHeight: `${labelHeight}px`,
        }}
      >
        <span style={{ fontSize: "9px", color: "#787b86", fontFamily: "'JetBrains Mono', monospace" }}>
          ADX+DI · Len 15 · Th 15
        </span>
        <span style={{ fontSize: "8px", color: "#42a5f5", fontFamily: "'JetBrains Mono', monospace" }}>● RSI</span>
        <span style={{ fontSize: "8px", color: "#ff9800", fontFamily: "'JetBrains Mono', monospace" }}>● Sig</span>
      </div>

      {/* MACD+RSI — remaining */}
      <MacdRsiPanel
        data={macdRsiData}
        height={macdHeight}
        onCrosshairMove={handleCrosshairMove}
        onChartReady={handleMacdChartReady}
      />
    </div>
  );
}
