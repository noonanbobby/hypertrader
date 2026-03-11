"use client";

import { useEffect, useRef } from "react";
import type { PnlDataPoint } from "@/types";
import { TrendingUp } from "lucide-react";

interface EquityCurveProps {
  data: PnlDataPoint[];
}

export function EquityCurve({ data }: EquityCurveProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    let chart: any = null;

    import("lightweight-charts").then(({ createChart, ColorType }) => {
      if (!containerRef.current) return;

      containerRef.current.innerHTML = "";

      chart = createChart(containerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "rgba(255,255,255,0.25)",
          fontFamily: "Inter, sans-serif",
          fontSize: 10,
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.03)" },
          horzLines: { color: "rgba(255,255,255,0.03)" },
        },
        width: containerRef.current.clientWidth,
        height: 350,
        rightPriceScale: {
          borderColor: "rgba(255,255,255,0.05)",
        },
        timeScale: {
          borderColor: "rgba(255,255,255,0.05)",
        },
        crosshair: {
          horzLine: { color: "rgba(255,255,255,0.08)", labelBackgroundColor: "#1a1f35" },
          vertLine: { color: "rgba(255,255,255,0.08)", labelBackgroundColor: "#1a1f35" },
        },
      });

      const series = chart.addAreaSeries({
        lineColor: "#3b82f6",
        topColor: "rgba(59,130,246,0.2)",
        bottomColor: "rgba(59,130,246,0.0)",
        lineWidth: 2,
      });

      const chartData = data.map((d) => ({
        time: d.timestamp.slice(0, 10),
        value: d.equity,
      }));

      series.setData(chartData);
      chart.timeScale().fitContent();

      const resizeObserver = new ResizeObserver(() => {
        if (containerRef.current) {
          chart.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      resizeObserver.observe(containerRef.current);

      return () => resizeObserver.disconnect();
    });

    return () => {
      chart?.remove();
    };
  }, [data]);

  return (
    <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] overflow-hidden">
      <div className="flex items-center gap-2 px-5 pt-5 pb-3">
        <TrendingUp className="h-4 w-4 text-blue-400/60" />
        <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
          Equity Curve
        </span>
      </div>
      {data.length === 0 ? (
        <div className="h-[350px] flex items-center justify-center text-white/20 text-sm">
          No equity data yet. Trades will generate snapshots.
        </div>
      ) : (
        <div ref={containerRef} className="w-full px-2 pb-2" />
      )}
    </div>
  );
}
