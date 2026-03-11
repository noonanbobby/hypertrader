"use client";

import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency, formatPrice, pnlColor, timeAgo } from "@/lib/utils";
import type { Trade } from "@/types";
import { ArrowUpRight, ArrowDownRight, History } from "lucide-react";

interface RecentTradesProps {
  trades: Trade[];
}

export function RecentTrades({ trades }: RecentTradesProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-white/30" />
          <CardTitle>Recent Trades</CardTitle>
        </div>
      </CardHeader>
      <div className="space-y-1 max-h-[380px] overflow-y-auto pr-1">
        {trades.length === 0 ? (
          <div className="text-center py-12">
            <div className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-white/[0.03] mb-3">
              <History className="h-6 w-6 text-white/10" />
            </div>
            <p className="text-white/30 text-sm">No trades yet</p>
          </div>
        ) : (
          trades.slice(0, 20).map((trade) => {
            const isLong = trade.side === "long";
            return (
              <div
                key={trade.id}
                className="flex items-center justify-between py-3 px-3 rounded-xl hover:bg-white/[0.03] transition-all duration-150 group"
              >
                <div className="flex items-center gap-3">
                  <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                    isLong ? "bg-emerald-500/10" : "bg-red-500/10"
                  }`}>
                    {isLong ? (
                      <ArrowUpRight className="h-4 w-4 text-emerald-400" />
                    ) : (
                      <ArrowDownRight className="h-4 w-4 text-red-400" />
                    )}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white">
                        {trade.symbol}
                      </span>
                      <span className={`text-[10px] font-bold uppercase ${
                        isLong ? "text-emerald-400" : "text-red-400"
                      }`}>
                        {isLong ? "LONG" : "SHORT"}
                      </span>
                    </div>
                    <span className="text-[11px] text-white/30 font-mono">
                      {trade.quantity} @ {formatPrice(trade.entry_price)}
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  {trade.status === "closed" ? (
                    <span className={`text-sm font-bold ${
                      trade.realized_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}>
                      {trade.realized_pnl >= 0 ? "+" : ""}{formatCurrency(trade.realized_pnl)}
                    </span>
                  ) : (
                    <span className="text-[10px] font-bold text-amber-400/70 uppercase tracking-wider">
                      Open
                    </span>
                  )}
                  <div className="text-[10px] text-white/20">
                    {timeAgo(trade.entry_time)}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
}
