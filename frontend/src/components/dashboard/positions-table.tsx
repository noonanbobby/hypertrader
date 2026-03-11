"use client";

import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency, formatPrice, formatPercent } from "@/lib/utils";
import type { Position } from "@/types";
import { Crosshair } from "lucide-react";

interface PositionsTableProps {
  positions: Position[];
}

export function PositionsTable({ positions }: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Crosshair className="h-4 w-4 text-white/30" />
            <CardTitle>Open Positions</CardTitle>
          </div>
        </CardHeader>
        <div className="text-center py-12">
          <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-white/[0.03] mb-4">
            <Crosshair className="h-7 w-7 text-white/10" />
          </div>
          <p className="text-white/30 text-sm">No open positions</p>
          <p className="text-white/15 text-xs mt-1">Waiting for signals...</p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Crosshair className="h-4 w-4 text-white/30" />
          <CardTitle>Open Positions</CardTitle>
        </div>
        <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-[10px] font-bold text-emerald-400">{positions.length} ACTIVE</span>
        </div>
      </CardHeader>
      <div className="overflow-x-auto -mx-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.04]">
              <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Symbol</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Side</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Lev</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Size</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Entry</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Mark</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Margin</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Unreal. P&L</th>
              <th className="text-right px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Notional</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const positive = pos.unrealized_pnl >= 0;
              return (
                <tr
                  key={pos.id}
                  className="border-b border-white/[0.03] table-row-hover"
                >
                  <td className="px-6 py-4">
                    <span className="font-semibold text-white">{pos.symbol}</span>
                    <span className="text-white/20 text-xs ml-1">PERP</span>
                  </td>
                  <td className="px-3 py-4">
                    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                      pos.side === "long"
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        : "bg-red-500/10 text-red-400 border border-red-500/20"
                    }`}>
                      {pos.side}
                    </span>
                  </td>
                  <td className="px-3 py-4">
                    <span className="inline-flex items-center rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-bold">
                      {pos.leverage}x
                    </span>
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/80">
                    {pos.quantity}
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/50">
                    {formatPrice(pos.entry_price)}
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white">
                    {formatPrice(pos.current_price)}
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/50">
                    {formatCurrency(pos.margin_used)}
                  </td>
                  <td className="px-3 py-4 text-right">
                    <span className={`font-bold ${positive ? "text-emerald-400" : "text-red-400"}`}>
                      {formatCurrency(pos.unrealized_pnl)}
                    </span>
                    <br />
                    <span className={`text-[10px] font-medium ${positive ? "text-emerald-400/60" : "text-red-400/60"}`}>
                      {formatPercent(pos.pnl_pct)}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right font-mono text-white/30">
                    {formatCurrency(pos.notional_value)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
