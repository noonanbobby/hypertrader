"use client";

import { useEffect, useRef, memo } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
  ColorType,
  LineStyle,
  CrosshairMode,
} from "lightweight-charts";
import type { CandleData, SupertrendPoint, SupertrendSignal } from "@/types";
import { COLORS } from "@/lib/constants";

interface PriceChartProps {
  candles: CandleData[];
  supertrendPoints: SupertrendPoint[];
  supertrendSignals: SupertrendSignal[];
  height: number;
  onCrosshairMove?: (time: Time | null) => void;
  onChartReady?: (chart: IChartApi) => void;
}

export const PriceChart = memo(function PriceChart({
  candles,
  supertrendPoints,
  supertrendSignals,
  height,
  onCrosshairMove,
  onChartReady,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const greenLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const redLineRef = useRef<ISeriesApi<"Line"> | null>(null);

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
      },
      timeScale: {
        borderColor: "rgba(42,46,57,0.5)",
        timeVisible: true,
        secondsVisible: false,
        barSpacing: 6,
        rightOffset: 5,
        visible: false, // hide on price panel, show on bottom MACD panel only
      },
      handleScroll: {
        vertTouchDrag: false,
        horzTouchDrag: true,
        pressedMouseMove: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        pinch: true,
      },
    });

    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: COLORS.bullish,
      downColor: COLORS.bearish,
      borderUpColor: COLORS.bullish,
      borderDownColor: COLORS.bearish,
      wickUpColor: COLORS.bullish,
      wickDownColor: COLORS.bearish,
    });
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeSeriesRef.current = volumeSeries;

    // Green supertrend line (bullish periods)
    const greenLine = chart.addLineSeries({
      color: COLORS.bullish,
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    greenLineRef.current = greenLine;

    // Red supertrend line (bearish periods)
    const redLine = chart.addLineSeries({
      color: COLORS.bearish,
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    redLineRef.current = redLine;

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
        color: c.close >= c.open ? "rgba(38,166,154,0.2)" : "rgba(239,83,80,0.2)",
      })),
    );
  }, [candles]);

  // Update supertrend — each direction only shows during its own period
  // Green line only during bullish, red line only during bearish
  // Transition points are duplicated so lines connect at direction changes
  useEffect(() => {
    if (!greenLineRef.current || !redLineRef.current || supertrendPoints.length === 0) return;

    const greenData: LineData[] = [];
    const redData: LineData[] = [];

    for (let i = 0; i < supertrendPoints.length; i++) {
      const pt = supertrendPoints[i];
      const time = pt.time as Time;

      if (pt.direction === "bullish") {
        greenData.push({ time, value: pt.value });
        // At direction change, add transition point to connect segments
        if (i > 0 && supertrendPoints[i - 1].direction === "bearish") {
          // Bridge: end the red line at this point too
          redData.push({ time, value: pt.value });
        }
      } else {
        redData.push({ time, value: pt.value });
        if (i > 0 && supertrendPoints[i - 1].direction === "bullish") {
          greenData.push({ time, value: pt.value });
        }
      }
    }

    greenLineRef.current.setData(greenData);
    redLineRef.current.setData(redData);
  }, [supertrendPoints]);

  // Update buy/sell markers
  useEffect(() => {
    if (!candleSeriesRef.current || supertrendSignals.length === 0) return;

    const markers = supertrendSignals.map((sig) => ({
      time: sig.time as Time,
      position: sig.type === "buy" ? ("belowBar" as const) : ("aboveBar" as const),
      color: sig.type === "buy" ? COLORS.bullish : COLORS.bearish,
      shape: sig.type === "buy" ? ("arrowUp" as const) : ("arrowDown" as const),
      text: sig.type === "buy" ? "Buy" : "Sell",
      size: 1,
    }));

    candleSeriesRef.current.setMarkers(markers);
  }, [supertrendSignals]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: `${height}px` }}
      role="img"
      aria-label="BTC price chart with Supertrend indicator"
    />
  );
});
