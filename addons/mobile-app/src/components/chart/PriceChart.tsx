"use client";

import { useEffect, useRef, memo } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
  ColorType,
  LineStyle,
  CrosshairMode,
} from "lightweight-charts";
import type { CandleData, EnrichedSTPoint, ChartMarker } from "@/types";
import { COLORS } from "@/lib/constants";

interface PriceChartProps {
  candles: CandleData[];
  stPoints: EnrichedSTPoint[];
  markers: ChartMarker[];
  height: number;
  onCrosshairMove?: (time: Time | null) => void;
  onChartReady?: (chart: IChartApi) => void;
}

export const PriceChart = memo(function PriceChart({
  candles,
  stPoints,
  markers,
  height,
  onCrosshairMove,
  onChartReady,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const stLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bgFillRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bgPanel },
        textColor: COLORS.textSecondary,
        fontSize: 10,
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: "rgba(42,46,57,0.3)" },
        horzLines: { color: "rgba(42,46,57,0.3)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(120,123,134,0.4)", width: 1, style: LineStyle.Dashed, labelBackgroundColor: COLORS.bgPanel },
        horzLine: { color: "rgba(120,123,134,0.4)", width: 1, style: LineStyle.Dashed, labelBackgroundColor: COLORS.bgPanel },
      },
      rightPriceScale: {
        borderColor: "rgba(42,46,57,0.5)",
        scaleMargins: { top: 0.05, bottom: 0.15 },
        minimumWidth: 60,
      },
      timeScale: {
        borderColor: "rgba(42,46,57,0.5)",
        timeVisible: true,
        secondsVisible: false,
        barSpacing: 6,
        rightOffset: 5,
        visible: false,
      },
      handleScroll: { vertTouchDrag: false, horzTouchDrag: true, pressedMouseMove: true },
      handleScale: { axisPressedMouseMove: true, pinch: true },
    });

    chartRef.current = chart;

    // Candles
    const candleSeries = chart.addCandlestickSeries({
      upColor: COLORS.bullish,
      downColor: COLORS.bearish,
      borderUpColor: COLORS.bullish,
      borderDownColor: COLORS.bearish,
      wickUpColor: COLORS.bullish,
      wickDownColor: COLORS.bearish,
    });
    candleSeriesRef.current = candleSeries;

    // Volume
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    volumeSeriesRef.current = volumeSeries;

    // Single ST line — we'll set color per-point via individual line segments
    // lightweight-charts doesn't support per-point colors on Line series,
    // so we use multiple line series: green, red, gray, orange
    // But only ONE is visible at any bar (the others have gaps).
    // Actually the simplest approach: use a single line series and update its data
    // with the line color encoded as separate series.
    // We'll use 4 line series — one per color — with gaps (NaN) where inactive.
    const stLine = chart.addLineSeries({
      color: COLORS.textSecondary, // fallback
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    stLineRef.current = stLine;

    chart.subscribeCrosshairMove((param) => {
      onCrosshairMove?.(param.time ?? null);
    });

    onChartReady?.(chart);

    const resizeObserver = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect;
      chart.applyOptions({ width });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // Update candle + volume data
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || candles.length === 0) return;

    candleSeriesRef.current.setData(
      candles.map((c) => ({
        time: c.time as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    volumeSeriesRef.current.setData(
      candles.map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open ? "rgba(38,166,154,0.15)" : "rgba(239,83,80,0.15)",
      })),
    );
  }, [candles]);

  // Update ST line — single line, color segments via lightweight-charts
  // Since lightweight-charts v4 doesn't support per-point colors on line series,
  // we need multiple line series with gaps. Let's use 4 line series.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || stPoints.length === 0) return;

    // Remove old ST line and recreate 4 colored lines
    if (stLineRef.current) {
      chart.removeSeries(stLineRef.current);
      stLineRef.current = null;
    }

    // Build 4 arrays — green, red, gray, orange — with gaps
    const COLOR_MAP = {
      green: COLORS.bullish,
      red: COLORS.bearish,
      gray: "#787b86",
      orange: "#ff9800",
    };

    const colorKeys = ["green", "red", "gray", "orange"] as const;
    const dataByColor: Record<string, LineData[]> = {};
    for (const ck of colorKeys) dataByColor[ck] = [];

    // For each point, add to the correct color array and bridge at transitions
    for (let i = 0; i < stPoints.length; i++) {
      const pt = stPoints[i];
      const time = pt.time as Time;
      const activeColor = pt.lineColor;

      // Add the point to the active color's array
      dataByColor[activeColor].push({ time, value: pt.value });

      // Bridge: if color changed from previous, add this point to the previous color too (for continuity)
      if (i > 0 && stPoints[i - 1].lineColor !== activeColor) {
        dataByColor[stPoints[i - 1].lineColor].push({ time, value: pt.value });
      }
    }

    // Create line series for each color
    const seriesRefs: ISeriesApi<"Line">[] = [];
    for (const ck of colorKeys) {
      if (dataByColor[ck].length === 0) continue;
      const s = chart.addLineSeries({
        color: COLOR_MAP[ck],
        lineWidth: 2,
        lineStyle: ck === "orange" ? LineStyle.Dotted : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData(dataByColor[ck]);
      seriesRefs.push(s);
    }

    return () => {
      // Cleanup on re-render
      seriesRefs.forEach((s) => {
        try { chart.removeSeries(s); } catch {}
      });
    };
  }, [stPoints]);

  // Markers — buy, sell, exit, unfiltered, executions
  useEffect(() => {
    if (!candleSeriesRef.current || markers.length === 0) return;

    // Sort markers by time (required by lightweight-charts)
    const sorted = [...markers].sort((a, b) => a.time - b.time);

    const lwMarkers = sorted.map((m) => {
      switch (m.type) {
        case "buy":
          return {
            time: m.time as Time,
            position: "belowBar" as const,
            color: COLORS.bullish,
            shape: "arrowUp" as const,
            text: "Buy",
            size: 1.5,
          };
        case "sell":
          return {
            time: m.time as Time,
            position: "aboveBar" as const,
            color: COLORS.bearish,
            shape: "arrowDown" as const,
            text: "Sell",
            size: 1.5,
          };
        case "exit":
          return {
            time: m.time as Time,
            position: "aboveBar" as const,
            color: "#ff9800",
            shape: "circle" as const,
            text: "X",
            size: 1,
          };
        case "unfilteredBull":
          return {
            time: m.time as Time,
            position: "belowBar" as const,
            color: "rgba(0,230,118,0.35)",
            shape: "circle" as const,
            text: "",
            size: 0.5,
          };
        case "unfilteredBear":
          return {
            time: m.time as Time,
            position: "aboveBar" as const,
            color: "rgba(255,23,68,0.35)",
            shape: "circle" as const,
            text: "",
            size: 0.5,
          };
        case "execBuy":
          return {
            time: m.time as Time,
            position: "belowBar" as const,
            color: "#00bcd4",
            shape: "circle" as const,
            text: "B",
            size: 1.2,
          };
        case "execSell":
          return {
            time: m.time as Time,
            position: "aboveBar" as const,
            color: COLORS.bearish,
            shape: "circle" as const,
            text: "S",
            size: 1.2,
          };
        default:
          return null;
      }
    }).filter(Boolean) as any[];

    candleSeriesRef.current.setMarkers(lwMarkers);
  }, [markers]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: `${height}px` }}
      role="img"
      aria-label="Price chart with Recovery SuperTrend"
    />
  );
});
