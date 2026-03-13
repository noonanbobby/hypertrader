"use client";

import { useState } from "react";
import { useDashboard, usePositions, useTrades, useStrategies } from "@/hooks/use-api";
import { useWebSocket } from "@/hooks/use-websocket";
import { updateStrategy, deleteStrategy } from "@/lib/api";
import { PortfolioValue } from "@/components/dashboard/portfolio-value";
import { PnlCards } from "@/components/dashboard/pnl-cards";
import { PositionsTable } from "@/components/dashboard/positions-table";
import { RecentTrades } from "@/components/dashboard/recent-trades";
import { MarketTicker } from "@/components/dashboard/market-ticker";
import { StrategyCard } from "@/components/strategies/strategy-card";
import { StrategyMetrics } from "@/components/strategies/strategy-metrics";
import { CreateStrategyDialog } from "@/components/strategies/create-strategy-dialog";
import { EditStrategyDialog } from "@/components/strategies/edit-strategy-dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import type { Strategy } from "@/types";
import {
  Activity,
  TrendingUp,
  Target,
  BarChart3,
  Trophy,
  Flame,
  Plus,
  Layers,
  FlaskConical,
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

export default function PaperTradingPage() {
  const { data: stats } = useDashboard();
  const { data: positions } = usePositions();
  const { data: trades } = useTrades();
  const { data: strategies, mutate } = useStrategies();
  const { subscribe } = useWebSocket();
  const { addToast } = useToast();

  const [showCreate, setShowCreate] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState<Strategy | null>(null);

  const handleToggle = async (id: number, status: string) => {
    try {
      await updateStrategy(id, { status } as any);
      mutate();
      addToast(`Strategy ${status}`, "success");
    } catch (err: any) {
      addToast(err.message, "error");
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this strategy and all its data?")) return;
    try {
      await deleteStrategy(id);
      mutate();
      addToast("Strategy deleted", "success");
    } catch (err: any) {
      addToast(err.message, "error");
    }
  };

  return (
    <div className="relative z-10 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 border border-amber-500/10">
            <FlaskConical className="h-5 w-5 text-amber-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Paper Trading</h1>
            <p className="text-xs text-white/30 mt-0.5">
              Simulated trading with strategy tracking
            </p>
          </div>
        </div>
      </div>

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
      <PositionsTable positions={positions ?? []} subscribe={subscribe} />

      {/* Recent Trades */}
      <RecentTrades trades={trades ?? []} />

      {/* Strategies Section */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-amber-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-white/30">
              Strategies
            </span>
            <span className="text-xs text-white/20">
              ({strategies?.length ?? 0})
            </span>
          </div>
          <Button onClick={() => setShowCreate(true)} className="h-8 text-xs">
            <Plus className="h-3.5 w-3.5" /> New Strategy
          </Button>
        </div>

        <StrategyMetrics strategies={strategies ?? []} />

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
          {(strategies ?? []).map((s) => (
            <StrategyCard
              key={s.id}
              strategy={s}
              onToggle={handleToggle}
              onDelete={handleDelete}
              onEdit={setEditingStrategy}
            />
          ))}
          {(strategies ?? []).length === 0 && (
            <div className="col-span-3 text-center py-12 text-white/20">
              No strategies yet. Create one to get started.
            </div>
          )}
        </div>
      </div>

      <CreateStrategyDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => mutate()}
      />

      <EditStrategyDialog
        strategy={editingStrategy}
        onClose={() => setEditingStrategy(null)}
        onUpdated={() => mutate()}
      />
    </div>
  );
}
