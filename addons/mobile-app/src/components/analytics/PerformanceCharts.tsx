"use client";

import { useEffect, useRef, memo } from "react";
import {
  createChart,
  type IChartApi,
  type Time,
  ColorType,
  LineStyle,
  CrosshairMode,
} from "lightweight-charts";
import type { PnlDataPoint } from "@/types";
import { COLORS } from "@/lib/constants";

interface ChartWrapperProps {
  title: string;
  children: React.ReactNode;
}

function ChartWrapper({ title, children }: ChartWrapperProps) {
  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
    >
      <div className="px-3 py-2 border-b" style={{ borderColor: "rgba(42,46,57,0.5)" }}>
        <span className="text-xs font-medium" style={{ color: "#787b86" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function useBaseChart(containerRef: React.RefObject<HTMLDivElement | null>, height: number) {
  const chartRef = useRef<IChartApi | null>(null);

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
      rightPriceScale: { borderColor: "rgba(42,46,57,0.5)" },
      timeScale: { borderColor: "rgba(42,46,57,0.5)", timeVisible: true, secondsVisible: false },
      handleScroll: { vertTouchDrag: false },
    });

    chartRef.current = chart;

    const resizeObserver = new ResizeObserver((entries) => {
      chart.applyOptions({ width: entries[0].contentRect.width });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [containerRef, height]);

  return chartRef;
}

/* ── Equity Curve ── */
interface EquityCurveProps {
  data: PnlDataPoint[];
  height?: number;
}

export const EquityCurve = memo(function EquityCurve({ data, height = 220 }: EquityCurveProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useBaseChart(containerRef, height);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || data.length === 0) return;

    const series = chart.addAreaSeries({
      lineColor: COLORS.accentBlue,
      lineWidth: 2,
      topColor: "rgba(41,98,255,0.3)",
      bottomColor: "rgba(41,98,255,0.02)",
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    });

    const lineData = data.map((d) => ({
      time: (new Date(d.timestamp).getTime() / 1000) as Time,
      value: d.equity,
    }));

    series.setData(lineData);
    chart.timeScale().fitContent();

    return () => {
      try { chart.removeSeries(series); } catch { /* already removed */ }
    };
  }, [data, chartRef]);

  return (
    <ChartWrapper title="Equity Curve">
      <div ref={containerRef} style={{ height: `${height}px` }} role="img" aria-label="Equity curve chart" />
    </ChartWrapper>
  );
});

/* ── Drawdown Chart ── */
interface DrawdownChartProps {
  data: PnlDataPoint[];
  height?: number;
}

export const DrawdownChart = memo(function DrawdownChart({ data, height = 160 }: DrawdownChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useBaseChart(containerRef, height);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || data.length === 0) return;

    // Calculate drawdown from equity curve
    let peak = -Infinity;
    const ddData = data.map((d) => {
      if (d.equity > peak) peak = d.equity;
      const dd = peak > 0 ? ((d.equity - peak) / peak) * 100 : 0;
      return {
        time: (new Date(d.timestamp).getTime() / 1000) as Time,
        value: dd,
      };
    });

    const series = chart.addAreaSeries({
      lineColor: COLORS.bearish,
      lineWidth: 1,
      topColor: "rgba(239,83,80,0.02)",
      bottomColor: "rgba(239,83,80,0.2)",
      priceLineVisible: false,
      lastValueVisible: true,
      invertFilledArea: true,
    });

    series.setData(ddData);
    chart.timeScale().fitContent();

    return () => {
      try { chart.removeSeries(series); } catch { /* already removed */ }
    };
  }, [data, chartRef]);

  return (
    <ChartWrapper title="Drawdown">
      <div ref={containerRef} style={{ height: `${height}px` }} role="img" aria-label="Drawdown chart" />
    </ChartWrapper>
  );
});

/* ── Daily PnL Bar Chart ── */
interface DailyPnlChartProps {
  data: PnlDataPoint[];
  height?: number;
}

export const DailyPnlChart = memo(function DailyPnlChart({ data, height = 160 }: DailyPnlChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useBaseChart(containerRef, height);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || data.length === 0) return;

    // Group by day and compute daily PnL
    const dailyMap = new Map<string, number>();
    let prevEquity = data[0].equity;

    for (const d of data) {
      const date = new Date(d.timestamp).toISOString().split("T")[0];
      const dailyPnl = d.equity - prevEquity;
      dailyMap.set(date, (dailyMap.get(date) ?? 0) + dailyPnl);
      prevEquity = d.equity;
    }

    const barData = Array.from(dailyMap.entries()).map(([date, pnl]) => ({
      time: date as Time,
      value: pnl,
      color: pnl >= 0 ? COLORS.bullish : COLORS.bearish,
    }));

    const series = chart.addHistogramSeries({
      priceLineVisible: false,
      lastValueVisible: false,
    });

    series.setData(barData);
    chart.timeScale().fitContent();

    return () => {
      try { chart.removeSeries(series); } catch { /* already removed */ }
    };
  }, [data, chartRef]);

  return (
    <ChartWrapper title="Daily P&L">
      <div ref={containerRef} style={{ height: `${height}px` }} role="img" aria-label="Daily P&L bar chart" />
    </ChartWrapper>
  );
});
