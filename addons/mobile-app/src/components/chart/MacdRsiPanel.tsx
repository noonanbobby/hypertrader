"use client";

import { useEffect, useRef, memo } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type HistogramData,
  type LineData,
  type Time,
  ColorType,
  LineStyle,
  CrosshairMode,
} from "lightweight-charts";
import type { MacdRsiPoint } from "@/types";
import { COLORS } from "@/lib/constants";

const HIST_COLORS: Record<MacdRsiPoint["histogramColor"], string> = {
  brightGreen: "#26a69a",
  paleGreen: "rgba(38,166,154,0.45)",
  brightRed: "#ef5350",
  paleRed: "rgba(239,83,80,0.45)",
};

interface MacdRsiPanelProps {
  data: MacdRsiPoint[];
  height: number;
  onCrosshairMove?: (time: Time | null) => void;
  onChartReady?: (chart: IChartApi) => void;
}

export const MacdRsiPanel = memo(function MacdRsiPanel({
  data,
  height,
  onCrosshairMove,
  onChartReady,
}: MacdRsiPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const histSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);

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
        horzLines: { color: "rgba(42,46,57,0.2)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(120,123,134,0.4)",
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: COLORS.bgPanel,
        },
        horzLine: {
          color: "rgba(120,123,134,0.4)",
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: COLORS.bgPanel,
        },
      },
      rightPriceScale: {
        borderColor: "rgba(42,46,57,0.5)",
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: "rgba(42,46,57,0.5)",
        timeVisible: true,
        secondsVisible: false,
        barSpacing: 6,
        rightOffset: 5,
      },
      handleScroll: { vertTouchDrag: false, horzTouchDrag: true, pressedMouseMove: true },
      handleScale: { axisPressedMouseMove: true, pinch: true },
    });

    chartRef.current = chart;

    // Histogram
    const histSeries = chart.addHistogramSeries({
      priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
      priceLineVisible: false,
      lastValueVisible: false,
      priceScaleId: "histogram",
    });
    chart.priceScale("histogram").applyOptions({
      scaleMargins: { top: 0.6, bottom: 0 },
    });
    histSeriesRef.current = histSeries;

    // RSI line (blue)
    const rsiSeries = chart.addLineSeries({
      color: COLORS.macdRsiBlue,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      priceScaleId: "rsi",
    });
    chart.priceScale("rsi").applyOptions({
      scaleMargins: { top: 0.05, bottom: 0.45 },
    });
    rsiSeriesRef.current = rsiSeries;

    // MACD Signal line (orange)
    const macdSignal = chart.addLineSeries({
      color: COLORS.accentOrange,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      priceScaleId: "macd",
    });
    chart.priceScale("macd").applyOptions({
      scaleMargins: { top: 0.05, bottom: 0.45 },
    });
    macdSignalRef.current = macdSignal;

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

  // Update data
  useEffect(() => {
    if (!histSeriesRef.current || !rsiSeriesRef.current || !macdSignalRef.current || data.length === 0) return;

    const histData: HistogramData[] = data.map((d) => ({
      time: d.time as Time,
      value: d.histogram,
      color: HIST_COLORS[d.histogramColor],
    }));
    histSeriesRef.current.setData(histData);

    const rsiData: LineData[] = data.map((d) => ({
      time: d.time as Time,
      value: d.rsi,
    }));
    rsiSeriesRef.current.setData(rsiData);

    const signalData: LineData[] = data.map((d) => ({
      time: d.time as Time,
      value: d.macdSignal,
    }));
    macdSignalRef.current.setData(signalData);
  }, [data]);

  return (
    <div
      ref={containerRef}
      className="w-full"
      style={{ height: `${height}px` }}
      role="img"
      aria-label="MACD and RSI combined indicator"
    />
  );
});
