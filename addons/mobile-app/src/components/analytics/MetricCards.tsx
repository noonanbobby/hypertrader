"use client";

import { memo } from "react";
import type { AnalyticsResponse } from "@/types";
import { formatPnl, formatPercent, formatUsd, formatNumber, pnlColor } from "@/lib/format";
import { Skeleton } from "@/components/ui/Skeleton";

interface MetricCardsProps {
  analytics: AnalyticsResponse | undefined;
  isLoading: boolean;
}

interface MetricConfig {
  label: string;
  getValue: (a: AnalyticsResponse) => string;
  getColor?: (a: AnalyticsResponse) => string;
}

const metrics: MetricConfig[] = [
  {
    label: "Total P&L",
    getValue: (a) => {
      const totalPnl = a.equity_curve.length > 0
        ? a.equity_curve[a.equity_curve.length - 1].pnl
        : 0;
      return formatPnl(totalPnl);
    },
    getColor: (a) => {
      const totalPnl = a.equity_curve.length > 0
        ? a.equity_curve[a.equity_curve.length - 1].pnl
        : 0;
      return pnlColor(totalPnl);
    },
  },
  {
    label: "Win Rate",
    getValue: (a) => formatPercent(a.win_rate).replace("+", ""),
    getColor: (a) => a.win_rate >= 50 ? "#26a69a" : "#ef5350",
  },
  {
    label: "Profit Factor",
    getValue: (a) => formatNumber(a.profit_factor),
    getColor: (a) => a.profit_factor >= 1 ? "#26a69a" : "#ef5350",
  },
  {
    label: "Sharpe Ratio",
    getValue: (a) => formatNumber(a.sharpe_ratio),
    getColor: (a) => a.sharpe_ratio >= 1 ? "#26a69a" : a.sharpe_ratio >= 0 ? "#ff9800" : "#ef5350",
  },
  {
    label: "Max Drawdown",
    getValue: (a) => formatPercent(-Math.abs(a.max_drawdown)),
    getColor: () => "#ef5350",
  },
  {
    label: "Avg Win",
    getValue: (a) => formatUsd(a.avg_win),
    getColor: () => "#26a69a",
  },
  {
    label: "Avg Loss",
    getValue: (a) => formatUsd(a.avg_loss),
    getColor: () => "#ef5350",
  },
  {
    label: "Total Trades",
    getValue: (a) => a.total_trades.toString(),
  },
];

export const MetricCards = memo(function MetricCards({ analytics, isLoading }: MetricCardsProps) {
  return (
    <div
      className="flex gap-3 overflow-x-auto px-4 pb-1"
      style={{ scrollSnapType: "x mandatory", WebkitOverflowScrolling: "touch" }}
    >
      {metrics.map((metric) => (
        <div
          key={metric.label}
          className="min-w-[130px] flex-shrink-0 rounded-xl border p-3"
          style={{
            backgroundColor: "#1e222d",
            borderColor: "rgba(42,46,57,0.6)",
            scrollSnapAlign: "start",
          }}
        >
          <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "#787b86" }}>
            {metric.label}
          </span>
          {isLoading || !analytics ? (
            <Skeleton height={18} width="70%" className="mt-1.5" />
          ) : (
            <p
              className="mt-1 font-mono text-base font-semibold tabular-nums"
              style={{ color: metric.getColor ? metric.getColor(analytics) : "#d1d4dc" }}
            >
              {metric.getValue(analytics)}
            </p>
          )}
        </div>
      ))}
    </div>
  );
});
