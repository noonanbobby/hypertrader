"use client";

import { useEffect, useRef, useState } from "react";
import type { Trade } from "@/types";

interface TradePriceChartProps {
  trade: Trade;
}

interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export function TradePriceChart({ trade }: TradePriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    let chart: any = null;
    let cancelled = false;

    async function buildChart() {
      try {
        setLoading(true);
        setError(null);

        // Calculate time range: 24h before entry to 24h after exit (or now)
        const entryMs = new Date(trade.entry_time).getTime();
        const exitMs = trade.exit_time
          ? new Date(trade.exit_time).getTime()
          : Date.now();
        const paddingMs = 24 * 60 * 60 * 1000; // 24 hours
        const startTime = entryMs - paddingMs;
        const endTime = exitMs + paddingMs;

        // Determine candle interval based on trade duration
        const durationMs = exitMs - entryMs;
        let interval = "15m";
        if (durationMs > 7 * 24 * 60 * 60 * 1000) interval = "4h";
        else if (durationMs > 2 * 24 * 60 * 60 * 1000) interval = "1h";
        else if (durationMs > 6 * 60 * 60 * 1000) interval = "15m";
        else interval = "5m";

        // Fetch candle data from Hyperliquid
        const res = await fetch("https://api.hyperliquid.xyz/info", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: "candleSnapshot",
            req: {
              coin: trade.symbol,
              interval,
              startTime,
              endTime,
            },
          }),
        });

        if (!res.ok) throw new Error("Failed to fetch candle data");

        const rawCandles = await res.json();
        if (cancelled) return;

        if (!Array.isArray(rawCandles) || rawCandles.length === 0) {
          setError("No candle data available for this symbol");
          setLoading(false);
          return;
        }

        // Parse candles
        const candles: CandleData[] = rawCandles.map((c: any) => ({
          time: Math.floor(c.t / 1000),
          open: parseFloat(c.o),
          high: parseFloat(c.h),
          low: parseFloat(c.l),
          close: parseFloat(c.c),
        }));

        if (!containerRef.current || cancelled) return;

        // Import and create chart
        const {
          createChart,
          ColorType,
          CrosshairMode,
          LineStyle,
        } = await import("lightweight-charts");

        if (!containerRef.current || cancelled) return;

        containerRef.current.innerHTML = "";

        chart = createChart(containerRef.current, {
          layout: {
            background: { type: ColorType.Solid, color: "transparent" },
            textColor: "rgba(255,255,255,0.25)",
            fontFamily: "Inter, sans-serif",
            fontSize: 10,
          },
          grid: {
            vertLines: { color: "rgba(255,255,255,0.02)" },
            horzLines: { color: "rgba(255,255,255,0.02)" },
          },
          width: containerRef.current.clientWidth,
          height: 300,
          rightPriceScale: {
            borderColor: "rgba(255,255,255,0.05)",
          },
          timeScale: {
            borderColor: "rgba(255,255,255,0.05)",
            timeVisible: true,
            secondsVisible: false,
          },
          crosshair: {
            mode: CrosshairMode.Normal,
            horzLine: {
              color: "rgba(255,255,255,0.08)",
              labelBackgroundColor: "#1a1f35",
            },
            vertLine: {
              color: "rgba(255,255,255,0.08)",
              labelBackgroundColor: "#1a1f35",
            },
          },
        });

        // Add candlestick series
        const candleSeries = chart.addCandlestickSeries({
          upColor: "#10b981",
          downColor: "#ef4444",
          borderUpColor: "#10b981",
          borderDownColor: "#ef4444",
          wickUpColor: "rgba(16,185,129,0.5)",
          wickDownColor: "rgba(239,68,68,0.5)",
        });

        candleSeries.setData(candles);

        // Entry price line
        const entryColor =
          trade.side === "long"
            ? "rgba(16,185,129,0.8)"
            : "rgba(239,68,68,0.8)";

        candleSeries.createPriceLine({
          price: trade.entry_price,
          color: entryColor,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `Entry ${trade.side === "long" ? "LONG" : "SHORT"}`,
        });

        // Exit price line (if closed)
        if (trade.exit_price) {
          const exitColor =
            trade.realized_pnl >= 0
              ? "rgba(16,185,129,0.6)"
              : "rgba(239,68,68,0.6)";

          candleSeries.createPriceLine({
            price: trade.exit_price,
            color: exitColor,
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: `Exit ${trade.realized_pnl >= 0 ? "+" : ""}$${trade.realized_pnl.toFixed(2)}`,
          });
        }

        // Add entry marker
        const entryTimeSec = Math.floor(entryMs / 1000);
        const markers: any[] = [
          {
            time: entryTimeSec,
            position: trade.side === "long" ? "belowBar" : "aboveBar",
            color: trade.side === "long" ? "#10b981" : "#ef4444",
            shape: trade.side === "long" ? "arrowUp" : "arrowDown",
            text: trade.side === "long" ? "BUY" : "SELL",
          },
        ];

        // Add exit marker
        if (trade.exit_time && trade.exit_price) {
          const exitTimeSec = Math.floor(
            new Date(trade.exit_time).getTime() / 1000
          );
          markers.push({
            time: exitTimeSec,
            position: trade.side === "long" ? "aboveBar" : "belowBar",
            color: trade.realized_pnl >= 0 ? "#10b981" : "#ef4444",
            shape: trade.side === "long" ? "arrowDown" : "arrowUp",
            text: "CLOSE",
          });
        }

        // Sort markers by time (required by lightweight-charts)
        markers.sort((a, b) => a.time - b.time);
        candleSeries.setMarkers(markers);

        chart.timeScale().fitContent();

        // Responsive resize
        const resizeObserver = new ResizeObserver(() => {
          if (containerRef.current && chart) {
            chart.applyOptions({
              width: containerRef.current.clientWidth,
            });
          }
        });
        resizeObserver.observe(containerRef.current);

        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError("Failed to load chart data");
          setLoading(false);
        }
      }
    }

    buildChart();

    return () => {
      cancelled = true;
      chart?.remove();
    };
  }, [trade]);

  return (
    <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.04]">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/25">
          {trade.symbol} Price Chart
        </span>
        <span className={`text-[10px] font-bold uppercase tracking-wider ${
          trade.side === "long" ? "text-emerald-400" : "text-red-400"
        }`}>
          {trade.side}
        </span>
      </div>
      {loading && (
        <div className="h-[300px] flex items-center justify-center">
          <div className="flex items-center gap-2 text-white/20 text-xs">
            <div className="h-3 w-3 border-2 border-blue-400/30 border-t-blue-400 rounded-full animate-spin" />
            Loading chart...
          </div>
        </div>
      )}
      {error && (
        <div className="h-[300px] flex items-center justify-center text-white/20 text-xs">
          {error}
        </div>
      )}
      <div
        ref={containerRef}
        className={`w-full ${loading || error ? "hidden" : ""}`}
      />
    </div>
  );
}
