"use client";

import { useAnalytics, useTrades } from "@/hooks/use-api";
import { EquityCurve } from "@/components/charts/equity-curve";
import { DrawdownChart } from "@/components/charts/drawdown-chart";
import { PnlCalendar } from "@/components/charts/pnl-calendar";
import { ReturnsHistogram } from "@/components/charts/returns-histogram";
import { formatCurrency } from "@/lib/utils";
import {
  BarChart3,
  Target,
  TrendingUp,
  TrendingDown,
  Percent,
  Clock,
  Zap,
  Activity,
} from "lucide-react";

export default function AnalyticsPage() {
  const { data: analytics } = useAnalytics();
  const { data: trades } = useTrades();

  const metrics = [
    {
      icon: Target,
      label: "Win Rate",
      value: `${analytics?.win_rate ?? 0}%`,
      color: "bg-emerald-500/10 text-emerald-400",
    },
    {
      icon: TrendingUp,
      label: "Avg Win",
      value: formatCurrency(analytics?.avg_win ?? 0),
      color: "bg-emerald-500/10 text-emerald-400",
      valueColor: "text-emerald-400",
    },
    {
      icon: TrendingDown,
      label: "Avg Loss",
      value: formatCurrency(analytics?.avg_loss ?? 0),
      color: "bg-red-500/10 text-red-400",
      valueColor: "text-red-400",
    },
    {
      icon: Zap,
      label: "Profit Factor",
      value: (analytics?.profit_factor ?? 0).toFixed(2),
      color: "bg-blue-500/10 text-blue-400",
    },
    {
      icon: Activity,
      label: "Max Drawdown",
      value: `${(analytics?.max_drawdown ?? 0).toFixed(2)}%`,
      color: "bg-red-500/10 text-red-400",
      valueColor: "text-red-400",
    },
    {
      icon: BarChart3,
      label: "Sharpe Ratio",
      value: (analytics?.sharpe_ratio ?? 0).toFixed(2),
      color: "bg-purple-500/10 text-purple-400",
    },
    {
      icon: Percent,
      label: "Total Trades",
      value: String(analytics?.total_trades ?? 0),
      color: "bg-amber-500/10 text-amber-400",
    },
    {
      icon: Clock,
      label: "Avg Duration",
      value: `${(analytics?.avg_trade_duration_hours ?? 0).toFixed(1)}h`,
      color: "bg-cyan-500/10 text-cyan-400",
    },
  ];

  return (
    <div className="relative z-10 space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/10">
          <BarChart3 className="h-5 w-5 text-purple-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Analytics</h1>
          <p className="text-xs text-white/30 mt-0.5">
            Performance metrics and visualizations
          </p>
        </div>
      </div>

      {/* Key Metrics */}
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
                <p className={`text-xl font-bold mt-0.5 ${m.valueColor ?? "text-white"}`}>
                  {m.value}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <EquityCurve data={analytics?.equity_curve ?? []} />

      <div className="grid grid-cols-2 gap-6">
        <DrawdownChart data={analytics?.equity_curve ?? []} />
        <ReturnsHistogram trades={trades ?? []} />
      </div>

      <PnlCalendar monthlyReturns={analytics?.monthly_returns ?? {}} />
    </div>
  );
}
