"use client";

import { formatCurrency, formatPrice, formatDate } from "@/lib/utils";
import type { Trade } from "@/types";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";

interface TradesTableProps {
  trades: Trade[];
  onSelect?: (trade: Trade) => void;
}

export function TradesTable({ trades, onSelect }: TradesTableProps) {
  if (trades.length === 0) {
    return (
      <div className="text-center py-16 text-white/30">
        No trades found
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-2xl gradient-border backdrop-blur-xl bg-white/[0.02]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/[0.06]">
            {["Time", "Symbol", "Side", "Lev", "Qty", "Entry", "Margin", "Notional", "Exit", "P&L", "P&L %", "Fees", "Status"].map((h) => (
              <th
                key={h}
                className={`px-4 py-3.5 text-[10px] font-semibold uppercase tracking-wider text-white/25 ${
                  ["Qty", "Entry", "Margin", "Notional", "Exit", "P&L", "P&L %", "Fees"].includes(h) ? "text-right" : "text-left"
                }`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const isLong = t.side === "long";
            return (
              <tr
                key={t.id}
                className="border-b border-white/[0.03] table-row-hover cursor-pointer transition-all duration-150"
                onClick={() => onSelect?.(t)}
              >
                <td className="px-4 py-3.5 text-white/30 text-xs font-mono">
                  {formatDate(t.entry_time)}
                </td>
                <td className="px-4 py-3.5">
                  <span className="font-semibold text-white">{t.symbol}</span>
                </td>
                <td className="px-4 py-3.5">
                  <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                    isLong
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                      : "bg-red-500/10 text-red-400 border border-red-500/20"
                  }`}>
                    {isLong ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownRight className="h-2.5 w-2.5" />}
                    {t.side}
                  </span>
                </td>
                <td className="px-4 py-3.5">
                  <span className="inline-flex items-center rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-bold">
                    {t.leverage}x
                  </span>
                </td>
                <td className="px-4 py-3.5 text-right font-mono text-white/60">
                  {t.quantity}
                </td>
                <td className="px-4 py-3.5 text-right font-mono text-white/40">
                  {formatPrice(t.entry_price)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono text-white/70">
                  {formatCurrency(t.margin_used)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono text-white/30">
                  {formatCurrency(t.notional_value)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono text-white/40">
                  {t.exit_price ? formatPrice(t.exit_price) : "—"}
                </td>
                <td className="px-4 py-3.5 text-right">
                  {t.status === "closed" ? (
                    <span className={`font-bold ${
                      t.realized_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}>
                      {t.realized_pnl >= 0 ? "+" : ""}{formatCurrency(t.realized_pnl)}
                    </span>
                  ) : (
                    <span className="text-white/20">—</span>
                  )}
                </td>
                <td className="px-4 py-3.5 text-right">
                  {t.status === "closed" && t.margin_used > 0 ? (
                    <span className={`font-bold text-xs ${
                      t.realized_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}>
                      {t.realized_pnl >= 0 ? "+" : ""}{((t.realized_pnl / t.margin_used) * 100).toFixed(2)}%
                    </span>
                  ) : (
                    <span className="text-white/20">—</span>
                  )}
                </td>
                <td className="px-4 py-3.5 text-right font-mono text-white/25">
                  {formatCurrency(t.fees)}
                </td>
                <td className="px-4 py-3.5">
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                    t.status === "open"
                      ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                      : "bg-white/5 text-white/30 border border-white/5"
                  }`}>
                    {t.status === "open" && <div className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />}
                    {t.status}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
