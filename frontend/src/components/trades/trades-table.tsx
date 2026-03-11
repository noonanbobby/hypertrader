"use client";

import { useEffect, useState, useCallback } from "react";
import { formatCurrency, formatPrice, formatDate } from "@/lib/utils";
import { closeTrade } from "@/lib/api";
import type { Trade } from "@/types";
import { ArrowUpRight, ArrowDownRight, X } from "lucide-react";

interface TradesTableProps {
  trades: Trade[];
  onSelect?: (trade: Trade) => void;
  onTradesClosed?: () => void;
}

function normalizeSymbol(symbol: string): string {
  let coin = symbol.toUpperCase().replace("-PERP", "").replace("/USD", "");
  for (const suffix of ["USDC", "USDT", "USD", "PERP"]) {
    if (coin.endsWith(suffix) && coin.length > suffix.length) {
      return coin.slice(0, -suffix.length);
    }
  }
  return coin;
}

function calcPnl(trade: Trade, currentPrice: number): number {
  const direction = trade.side === "long" ? 1 : -1;
  return direction * (currentPrice - trade.entry_price) * trade.quantity;
}

export function TradesTable({ trades, onSelect, onTradesClosed }: TradesTableProps) {
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [closingId, setClosingId] = useState<number | null>(null);

  const openTrades = trades.filter((t) => t.status === "open");

  const fetchPrices = useCallback(async () => {
    if (openTrades.length === 0) return;
    try {
      const res = await fetch("https://api.hyperliquid.xyz/info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "allMids" }),
      });
      if (!res.ok) return;
      const data: Record<string, string> = await res.json();
      const prices: Record<string, number> = {};
      for (const [k, v] of Object.entries(data)) {
        prices[k] = parseFloat(v);
      }
      setLivePrices(prices);
    } catch {}
  }, [openTrades.length]);

  useEffect(() => {
    fetchPrices();
    const interval = setInterval(fetchPrices, 5000);
    return () => clearInterval(interval);
  }, [fetchPrices]);

  const handleClose = async (e: React.MouseEvent, trade: Trade) => {
    e.stopPropagation();
    if (closingId) return;
    if (!confirm(`Close ${trade.side} ${trade.symbol} position?`)) return;
    setClosingId(trade.id);
    try {
      await closeTrade(trade.id);
      onTradesClosed?.();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to close trade");
    } finally {
      setClosingId(null);
    }
  };

  if (trades.length === 0) {
    return (
      <div className="text-center py-16 text-white/30">
        No trades found
      </div>
    );
  }

  const headers = ["Time", "Symbol", "Side", "Lev", "Qty", "Entry", "Margin", "Notional", "Mark", "Exit", "P&L", "P&L %", "Fees", "Status", ""];
  const rightAligned = ["Qty", "Entry", "Margin", "Notional", "Mark", "Exit", "P&L", "P&L %", "Fees"];

  return (
    <div className="overflow-x-auto rounded-2xl gradient-border backdrop-blur-xl bg-white/[0.02]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/[0.06]">
            {headers.map((h) => (
              <th
                key={h}
                className={`px-4 py-3.5 text-[10px] font-semibold uppercase tracking-wider text-white/25 ${
                  rightAligned.includes(h) ? "text-right" : "text-left"
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
            const isOpen = t.status === "open";
            const coin = normalizeSymbol(t.symbol);
            const markPrice = livePrices[coin];
            const pnl = isOpen && markPrice ? calcPnl(t, markPrice) : t.realized_pnl;
            const pnlPct = t.margin_used > 0 ? (pnl / t.margin_used) * 100 : 0;
            const hasPnl = isOpen ? !!markPrice : t.status === "closed";

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
                <td className="px-4 py-3.5 text-right font-mono">
                  {isOpen && markPrice ? (
                    <span className="text-blue-400">{formatPrice(markPrice)}</span>
                  ) : (
                    <span className="text-white/20">—</span>
                  )}
                </td>
                <td className="px-4 py-3.5 text-right font-mono text-white/40">
                  {t.exit_price ? formatPrice(t.exit_price) : "—"}
                </td>
                <td className="px-4 py-3.5 text-right">
                  {hasPnl ? (
                    <span className={`font-bold ${
                      pnl >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}>
                      {pnl >= 0 ? "+" : ""}{formatCurrency(pnl)}
                    </span>
                  ) : (
                    <span className="text-white/20">—</span>
                  )}
                </td>
                <td className="px-4 py-3.5 text-right">
                  {hasPnl && t.margin_used > 0 ? (
                    <span className={`font-bold text-xs ${
                      pnl >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}>
                      {pnl >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
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
                <td className="px-4 py-3.5">
                  {isOpen && (
                    <button
                      onClick={(e) => handleClose(e, t)}
                      disabled={closingId === t.id}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wider bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                    >
                      {closingId === t.id ? (
                        <div className="h-2.5 w-2.5 border-2 border-red-400/30 border-t-red-400 rounded-full animate-spin" />
                      ) : (
                        <X className="h-2.5 w-2.5" />
                      )}
                      Close
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
