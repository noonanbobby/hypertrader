"use client";

import { memo } from "react";
import type { Trade } from "@/types";
import { formatPrice, formatPnl, formatUsd, formatTimestamp, pnlColor } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";

interface TradeCardProps {
  trade: Trade;
  onTap: (trade: Trade) => void;
}

export const TradeCard = memo(function TradeCard({ trade, onTap }: TradeCardProps) {
  const isLong = trade.side.toLowerCase() === "long";
  const hasPnl = trade.realized_pnl !== null && trade.status === "closed";

  return (
    <button
      onClick={() => onTap(trade)}
      className="w-full rounded-xl border p-3 text-left transition-default active:scale-[0.98]"
      style={{
        backgroundColor: "#1e222d",
        borderColor: "rgba(42,46,57,0.6)",
      }}
      aria-label={`${trade.symbol} ${trade.side} trade, ${trade.status}`}
    >
      {/* Top row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold" style={{ color: "#d1d4dc" }}>
            {trade.symbol}
          </span>
          <Badge variant={isLong ? "long" : "short"}>
            {trade.side.toUpperCase()}
          </Badge>
          <Badge variant={trade.status === "open" ? "info" : "neutral"} size="sm">
            {trade.status.toUpperCase()}
          </Badge>
        </div>
        {hasPnl && (
          <span
            className="font-mono text-sm font-semibold tabular-nums"
            style={{ color: pnlColor(trade.realized_pnl!) }}
          >
            {formatPnl(trade.realized_pnl!)}
          </span>
        )}
      </div>

      {/* Data rows */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        <DataCell label="Entry" value={formatPrice(trade.entry_price)} />
        {trade.exit_price !== null ? (
          <DataCell label="Exit" value={formatPrice(trade.exit_price)} />
        ) : (
          <DataCell label="Qty" value={trade.quantity.toFixed(4)} />
        )}
        <DataCell label="Notional" value={formatUsd(trade.notional_value)} />
        <DataCell label="Fees" value={formatUsd(trade.fees)} />
      </div>

      {/* Timestamp */}
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10px]" style={{ color: "#787b86" }}>
          {formatTimestamp(trade.entry_time)}
        </span>
        {trade.exit_time && (
          <span className="text-[10px]" style={{ color: "#787b86" }}>
            → {formatTimestamp(trade.exit_time)}
          </span>
        )}
      </div>
    </button>
  );
});

function DataCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px]" style={{ color: "#787b86" }}>{label}</span>
      <span className="font-mono text-xs tabular-nums" style={{ color: "#d1d4dc" }}>{value}</span>
    </div>
  );
}
