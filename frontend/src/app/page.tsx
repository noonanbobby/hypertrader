"use client";

import { useDashboard, usePositions, useTrades, useStrategies } from "@/hooks/use-api";
import { PortfolioValue } from "@/components/dashboard/portfolio-value";
import { PnlCards } from "@/components/dashboard/pnl-cards";
import { PositionsTable } from "@/components/dashboard/positions-table";
import { RecentTrades } from "@/components/dashboard/recent-trades";
import { StrategyCards } from "@/components/dashboard/strategy-cards";
import { MarketTicker } from "@/components/dashboard/market-ticker";
import { Card, CardTitle } from "@/components/ui/card";
import {
  Activity,
  TrendingUp,
  Target,
  BarChart3,
  Trophy,
  Flame,
} from "lucide-react";
import { formatCurrency } from "@/lib/utils";

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="gradient-border rounded-2xl p-5 backdrop-blur-xl bg-white/[0.02]">
      <div className="flex items-center gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-white/30">
            {label}
          </p>
          <p className="text-xl font-bold text-white mt-0.5">{value}</p>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: stats } = useDashboard();
  const { data: positions } = usePositions();
  const { data: trades } = useTrades();
  const { data: strategies } = useStrategies();

  return (
    <div className="relative z-10 space-y-6">
      {/* Market Ticker */}
      <MarketTicker />

      {/* Top Stats Row */}
      <div className="grid grid-cols-5 gap-4">
        <PortfolioValue
          totalEquity={stats?.total_equity ?? 0}
          totalPnl={stats?.total_pnl ?? 0}
        />
        <PnlCards
          daily={stats?.daily_pnl ?? 0}
          weekly={stats?.weekly_pnl ?? 0}
          monthly={stats?.monthly_pnl ?? 0}
        />
      </div>

      {/* Quick Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard
          icon={Activity}
          label="Open Positions"
          value={stats?.open_positions ?? 0}
          color="bg-blue-500/10 text-blue-400"
        />
        <StatCard
          icon={Trophy}
          label="Win Rate"
          value={`${stats?.win_rate ?? 0}%`}
          color="bg-emerald-500/10 text-emerald-400"
        />
        <StatCard
          icon={Flame}
          label="Best Trade"
          value={formatCurrency(stats?.best_trade ?? 0)}
          color="bg-amber-500/10 text-amber-400"
        />
        <StatCard
          icon={BarChart3}
          label="Total Trades"
          value={stats?.total_trades ?? 0}
          color="bg-purple-500/10 text-purple-400"
        />
      </div>

      {/* Positions */}
      <PositionsTable positions={positions ?? []} />

      {/* Bottom Grid */}
      <div className="grid grid-cols-2 gap-6">
        <RecentTrades trades={trades ?? []} />
        <div>
          <div className="flex items-center gap-2 mb-4">
            <Target className="h-4 w-4 text-white/20" />
            <span className="text-xs font-semibold uppercase tracking-wider text-white/30">
              Strategy Performance
            </span>
          </div>
          <div className="grid grid-cols-1 gap-4">
            <StrategyCards strategies={strategies ?? []} />
          </div>
        </div>
      </div>
    </div>
  );
}
