"use client";

import { formatCurrency, formatPnl, pnlColor } from "@/lib/utils";
import type { Strategy } from "@/types";
import { DollarSign, TrendingUp, Hash, Target } from "lucide-react";

interface StrategyMetricsProps {
  strategies: Strategy[];
}

export function StrategyMetrics({ strategies }: StrategyMetricsProps) {
  const totalPnl = strategies.reduce((sum, s) => sum + s.total_pnl, 0);
  const totalEquity = strategies.reduce((sum, s) => sum + s.current_equity, 0);
  const totalTrades = strategies.reduce((sum, s) => sum + s.total_trades, 0);
  const totalWins = strategies.reduce((sum, s) => sum + s.winning_trades, 0);
  const overallWinRate = totalTrades > 0 ? (totalWins / totalTrades) * 100 : 0;

  const metrics = [
    {
      icon: TrendingUp,
      label: "Total P&L",
      value: formatPnl(totalPnl),
      color: totalPnl >= 0
        ? "bg-emerald-500/10 text-emerald-400"
        : "bg-red-500/10 text-red-400",
      valueColor: totalPnl >= 0 ? "text-emerald-400" : "text-red-400",
    },
    {
      icon: DollarSign,
      label: "Total Equity",
      value: formatCurrency(totalEquity),
      color: "bg-blue-500/10 text-blue-400",
      valueColor: "text-white",
    },
    {
      icon: Hash,
      label: "Total Trades",
      value: String(totalTrades),
      color: "bg-purple-500/10 text-purple-400",
      valueColor: "text-white",
    },
    {
      icon: Target,
      label: "Win Rate",
      value: `${overallWinRate.toFixed(1)}%`,
      color: "bg-amber-500/10 text-amber-400",
      valueColor: "text-white",
    },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {metrics.map((m) => (
        <div key={m.label} className="gradient-border rounded-2xl p-5 backdrop-blur-xl bg-white/[0.02]">
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${m.color}`}>
              <m.icon className="h-5 w-5" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-white/25">
                {m.label}
              </p>
              <p className={`text-xl font-bold mt-0.5 ${m.valueColor}`}>{m.value}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
