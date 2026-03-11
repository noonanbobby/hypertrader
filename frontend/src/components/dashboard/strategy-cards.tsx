"use client";

import { Card } from "@/components/ui/card";
import { formatCurrency, formatPnl } from "@/lib/utils";
import type { Strategy } from "@/types";
import { Target, TrendingUp, Trophy, AlertTriangle } from "lucide-react";

interface StrategyCardsProps {
  strategies: Strategy[];
}

export function StrategyCards({ strategies }: StrategyCardsProps) {
  if (strategies.length === 0) {
    return (
      <Card className="col-span-full">
        <div className="text-center py-12">
          <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-white/[0.03] mb-4">
            <Target className="h-7 w-7 text-white/10" />
          </div>
          <p className="text-white/30 text-sm">No strategies yet</p>
          <p className="text-white/15 text-xs mt-1">
            Send a webhook to get started
          </p>
        </div>
      </Card>
    );
  }

  return (
    <>
      {strategies.map((s) => {
        const positive = s.total_pnl >= 0;
        return (
          <div key={s.id} className="gradient-border rounded-2xl p-5 backdrop-blur-xl bg-white/[0.02] hover:bg-white/[0.04] transition-all duration-300">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-semibold text-white">
                {s.name}
              </span>
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                s.status === "active"
                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                  : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
              }`}>
                {s.status}
              </span>
            </div>
            <div className={`text-2xl font-bold mb-4 ${
              positive ? "text-gradient-green" : "text-gradient-red"
            }`}>
              {formatPnl(s.total_pnl)}
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                { icon: Wallet2, label: "Equity", value: formatCurrency(s.current_equity) },
                { icon: Trophy, label: "Win Rate", value: `${s.win_rate}%` },
                { icon: TrendingUp, label: "Trades", value: `${s.winning_trades}/${s.total_trades}` },
                { icon: AlertTriangle, label: "Drawdown", value: `${s.current_drawdown.toFixed(1)}%`, danger: true },
              ].map((item) => (
                <div key={item.label} className="rounded-lg bg-white/[0.02] p-2">
                  <p className="text-[10px] text-white/25 uppercase tracking-wider">{item.label}</p>
                  <p className={`text-xs font-semibold mt-0.5 ${item.danger ? "text-red-400/80" : "text-white/70"}`}>
                    {item.value}
                  </p>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </>
  );
}

function Wallet2(props: any) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M17 14h.01"/><path d="M7 7h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14"/></svg>
  );
}
