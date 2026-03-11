"use client";

import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatCurrency, formatPrice, formatDate } from "@/lib/utils";
import { TradePriceChart } from "@/components/charts/trade-price-chart";
import type { Trade } from "@/types";
import {
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  DollarSign,
  Hash,
  TrendingUp,
  TrendingDown,
} from "lucide-react";

interface TradeDetailDialogProps {
  trade: Trade | null;
  onClose: () => void;
}

export function TradeDetailDialog({ trade, onClose }: TradeDetailDialogProps) {
  if (!trade) return null;

  const isLong = trade.side === "long";
  const isProfit = trade.realized_pnl >= 0;

  return (
    <Dialog open={!!trade} onClose={onClose} size="xl">
      <DialogHeader>
        <div className="flex items-center gap-3">
          <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${
            isLong
              ? "bg-emerald-500/10 border border-emerald-500/20"
              : "bg-red-500/10 border border-red-500/20"
          }`}>
            {isLong ? (
              <ArrowUpRight className="h-4 w-4 text-emerald-400" />
            ) : (
              <ArrowDownRight className="h-4 w-4 text-red-400" />
            )}
          </div>
          <div>
            <DialogTitle>
              {trade.symbol} #{trade.id}
            </DialogTitle>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-[10px] font-bold uppercase tracking-wider ${
                isLong ? "text-emerald-400" : "text-red-400"
              }`}>
                {trade.side}
              </span>
              <span className="text-white/10">|</span>
              <span className="text-[10px] font-bold text-blue-400">{trade.leverage}x</span>
              <span className="text-white/10">|</span>
              <span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider ${
                trade.status === "open"
                  ? "text-amber-400"
                  : "text-white/30"
              }`}>
                {trade.status === "open" && (
                  <div className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
                )}
                {trade.status}
              </span>
            </div>
          </div>
        </div>
      </DialogHeader>

      <div className="space-y-4">
        {/* Price Chart */}
        <TradePriceChart trade={trade} />

        {/* Trade Metrics Grid */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl bg-white/[0.03] border border-white/[0.04] p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <DollarSign className="h-3 w-3 text-white/15" />
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                Entry Price
              </p>
            </div>
            <p className="text-sm font-mono font-bold text-white">
              ${formatPrice(trade.entry_price)}
            </p>
          </div>
          <div className="rounded-xl bg-white/[0.03] border border-white/[0.04] p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <DollarSign className="h-3 w-3 text-white/15" />
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                Exit Price
              </p>
            </div>
            <p className="text-sm font-mono font-bold text-white">
              {trade.exit_price ? `$${formatPrice(trade.exit_price)}` : "—"}
            </p>
          </div>
          <div className="rounded-xl bg-white/[0.03] border border-white/[0.04] p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <Hash className="h-3 w-3 text-white/15" />
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                Quantity
              </p>
            </div>
            <p className="text-sm font-mono font-bold text-white/70">
              {trade.quantity}
            </p>
          </div>
          <div className="rounded-xl bg-white/[0.03] border border-white/[0.04] p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <DollarSign className="h-3 w-3 text-white/15" />
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                Margin Used
              </p>
            </div>
            <p className="text-sm font-mono font-bold text-white/70">
              {formatCurrency(trade.margin_used)}
            </p>
          </div>
          <div className="rounded-xl bg-white/[0.03] border border-white/[0.04] p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <DollarSign className="h-3 w-3 text-white/15" />
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                Notional
              </p>
            </div>
            <p className="text-sm font-mono font-bold text-white/30">
              {formatCurrency(trade.notional_value)}
            </p>
          </div>
          <div className="rounded-xl bg-white/[0.03] border border-white/[0.04] p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <DollarSign className="h-3 w-3 text-white/15" />
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                Fees
              </p>
            </div>
            <p className="text-sm font-mono font-bold text-white/30">
              {formatCurrency(trade.fees)}
            </p>
          </div>
          <div className={`rounded-xl p-3 ${
            trade.status === "closed"
              ? isProfit
                ? "bg-emerald-500/5 border border-emerald-500/10"
                : "bg-red-500/5 border border-red-500/10"
              : "bg-white/[0.03] border border-white/[0.04]"
          }`}>
            <div className="flex items-center gap-1.5 mb-1">
              {isProfit ? (
                <TrendingUp className="h-3 w-3 text-emerald-400/40" />
              ) : (
                <TrendingDown className="h-3 w-3 text-red-400/40" />
              )}
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                Realized P&L
              </p>
            </div>
            <p className={`text-sm font-mono font-bold ${
              trade.status === "closed"
                ? isProfit ? "text-emerald-400" : "text-red-400"
                : "text-white/20"
            }`}>
              {trade.status === "closed"
                ? `${isProfit ? "+" : ""}${formatCurrency(trade.realized_pnl)}`
                : "—"}
            </p>
          </div>
        </div>

        {/* Timestamps */}
        <div className="flex items-center gap-6 text-xs pt-1">
          <div className="flex items-center gap-1.5 text-white/20">
            <Clock className="h-3 w-3" />
            <span>Entry: {formatDate(trade.entry_time)}</span>
          </div>
          {trade.exit_time && (
            <div className="flex items-center gap-1.5 text-white/20">
              <Clock className="h-3 w-3" />
              <span>Exit: {formatDate(trade.exit_time)}</span>
            </div>
          )}
        </div>

        {/* Message */}
        {trade.message && (
          <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-3 py-2.5">
            <p className="text-[10px] text-white/15 font-semibold uppercase tracking-wider mb-1">Message</p>
            <p className="text-xs text-white/40">{trade.message}</p>
          </div>
        )}
      </div>
    </Dialog>
  );
}
