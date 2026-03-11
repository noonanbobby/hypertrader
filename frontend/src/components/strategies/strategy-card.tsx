"use client";

import { Button } from "@/components/ui/button";
import { formatCurrency, formatPnl } from "@/lib/utils";
import type { Strategy } from "@/types";
import { Pause, Play, Trash2, Pencil, TrendingUp, TrendingDown } from "lucide-react";

interface StrategyCardProps {
  strategy: Strategy;
  onToggle: (id: number, status: string) => void;
  onDelete: (id: number) => void;
  onEdit: (strategy: Strategy) => void;
}

export function StrategyCard({ strategy: s, onToggle, onDelete, onEdit }: StrategyCardProps) {
  const isPositive = s.total_pnl >= 0;

  return (
    <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5 transition-all duration-200 hover:bg-white/[0.04]">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-bold text-white">{s.name}</h3>
          {s.description && (
            <p className="text-[10px] text-white/25 mt-0.5">{s.description}</p>
          )}
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
          s.status === "active"
            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
            : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
        }`}>
          {s.status === "active" && <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />}
          {s.status}
        </span>
      </div>

      <div className="flex items-center gap-2 mb-4">
        {isPositive ? (
          <TrendingUp className="h-5 w-5 text-emerald-400" />
        ) : (
          <TrendingDown className="h-5 w-5 text-red-400" />
        )}
        <span className={`text-2xl font-bold ${isPositive ? "text-gradient-green" : "text-gradient-red"}`}>
          {formatPnl(s.total_pnl)}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4">
        {[
          { label: "Equity", value: formatCurrency(s.current_equity) },
          { label: "Allocated", value: formatCurrency(s.allocated_capital) },
          { label: "Win Rate", value: `${s.win_rate}%` },
          { label: "Trades", value: `${s.winning_trades}/${s.total_trades}` },
          { label: "Max Pos.", value: `${s.max_position_pct}%` },
          { label: "Drawdown", value: `${s.current_drawdown.toFixed(1)}%`, isRed: true },
        ].map((item) => (
          <div key={item.label} className="rounded-lg bg-white/[0.03] px-2.5 py-2">
            <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">{item.label}</p>
            <p className={`text-xs font-bold mt-0.5 ${item.isRed ? "text-red-400" : "text-white/70"}`}>
              {item.value}
            </p>
          </div>
        ))}
      </div>

      <div className="flex gap-2 border-t border-white/[0.04] pt-4">
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={() =>
            onToggle(s.id, s.status === "active" ? "paused" : "active")
          }
        >
          {s.status === "active" ? (
            <>
              <Pause className="h-3 w-3" /> Pause
            </>
          ) : (
            <>
              <Play className="h-3 w-3" /> Resume
            </>
          )}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onEdit(s)}
        >
          <Pencil className="h-3 w-3" />
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={() => onDelete(s.id)}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}
