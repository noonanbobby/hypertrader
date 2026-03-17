"use client";

import { useEffect, useRef, memo } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type HistogramData,
  type Time,
  ColorType,
  LineStyle,
  CrosshairMode,
} from "lightweight-charts";
import type { SqueezePoint } from "@/types";
import { COLORS } from "@/lib/constants";

const SQZ_COLORS: Record<SqueezePoint["color"], string> = {
  brightGreen: "#00e676",
  darkGreen: "#26a69a",
  brightRed: "#ff1744",
  darkRed: "#b71c1c",
};

interface SqueezePanelProps {
  data: SqueezePoint[];
  height: number;
  onCrosshairMove?: (time: Time | null) => void;
  onChartReady?: (chart: IChartApi) => void;
}

export const SqueezePanel = memo(function SqueezePanel({
  data,
  height,
  onCrosshairMove,
  onChartReady,
}: SqueezePanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const histSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const dotSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

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
        visible: false,
        barSpacing: 6,
        rightOffset: 5,
      },
      handleScroll: { vertTouchDrag: false, horzTouchDrag: true, pressedMouseMove: true },
      handleScale: { axisPressedMouseMove: true, pinch: true },
    });

    chartRef.current = chart;

    // Histogram bars
    const histSeries = chart.addHistogramSeries({
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    histSeriesRef.current = histSeries;

    // Squeeze dots on zero line — use a line series with markers
    const dotSeries = chart.addLineSeries({
      color: "transparent",
      lineWidth: 1,
      lineVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    dotSeriesRef.current = dotSeries;

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
    if (!histSeriesRef.current || !dotSeriesRef.current || data.length === 0) return;

    const histData: HistogramData[] = data.map((d) => ({
      time: d.time as Time,
      value: d.value,
      color: SQZ_COLORS[d.color],
    }));
    histSeriesRef.current.setData(histData);

    // Zero-line dots for squeeze state
    const dotData = data.map((d) => ({
      time: d.time as Time,
      value: 0,
    }));
    dotSeriesRef.current.setData(dotData);

    // Use markers for squeeze dots
    const markers = data.map((d) => ({
      time: d.time as Time,
      position: "inBar" as const,
      color: d.squeezeOn ? COLORS.bearish : COLORS.textSecondary,
      shape: "circle" as const,
      text: "",
      size: 0.5,
    }));
    dotSeriesRef.current.setMarkers(markers);
  }, [data]);

  return (
    <div
      ref={containerRef}
      className="w-full"
      style={{ height: `${height}px` }}
      role="img"
      aria-label="Squeeze Momentum indicator"
    />
  );
});
