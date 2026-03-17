"use client";

import { memo } from "react";
import type { Trade } from "@/types";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { Badge } from "@/components/ui/Badge";
import { formatPrice, formatPnl, formatUsd, formatPercent, formatTimestamp, pnlColor } from "@/lib/format";

interface TradeDetailProps {
  trade: Trade | null;
  open: boolean;
  onClose: () => void;
}

export const TradeDetail = memo(function TradeDetail({ trade, open, onClose }: TradeDetailProps) {
  if (!trade) return null;

  const isLong = trade.side.toLowerCase() === "long";
  const hasPnl = trade.realized_pnl !== null && trade.status === "closed";
  const pnlPct =
    hasPnl && trade.entry_price > 0 && trade.exit_price !== null
      ? ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100 * (isLong ? 1 : -1)
      : null;

  return (
    <BottomSheet open={open} onClose={onClose} title="Trade Details" snapPoints={[0.6]}>
      <div className="flex flex-col gap-4 py-2">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-mono text-lg font-bold" style={{ color: "#d1d4dc" }}>
              {trade.symbol}
            </span>
            <Badge variant={isLong ? "long" : "short"} size="md">
              {trade.side.toUpperCase()}
            </Badge>
          </div>
          <Badge variant={trade.status === "open" ? "info" : "neutral"} size="md">
            {trade.status.toUpperCase()}
          </Badge>
        </div>

        {/* P&L banner */}
        {hasPnl && (
          <div
            className="flex items-center justify-between rounded-xl p-4"
            style={{
              backgroundColor: trade.realized_pnl! >= 0
                ? "rgba(38,166,154,0.1)"
                : "rgba(239,83,80,0.1)",
              border: `1px solid ${trade.realized_pnl! >= 0 ? "rgba(38,166,154,0.2)" : "rgba(239,83,80,0.2)"}`,
            }}
          >
            <div>
              <span className="text-[10px] uppercase tracking-wider" style={{ color: "#787b86" }}>
                Realized P&L
              </span>
              <p
                className="font-mono text-xl font-bold tabular-nums"
                style={{ color: pnlColor(trade.realized_pnl!) }}
              >
                {formatPnl(trade.realized_pnl!)}
              </p>
            </div>
            {pnlPct !== null && (
              <span
                className="font-mono text-lg font-semibold tabular-nums"
                style={{ color: pnlColor(pnlPct) }}
              >
                {formatPercent(pnlPct)}
              </span>
            )}
          </div>
        )}

        {/* Detail rows */}
        <div
          className="rounded-xl border"
          style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
        >
          <DetailRow label="Strategy" value={trade.strategy_name} />
          <DetailRow label="Entry Price" value={formatPrice(trade.entry_price)} mono />
          {trade.exit_price !== null && (
            <DetailRow label="Exit Price" value={formatPrice(trade.exit_price)} mono />
          )}
          <DetailRow label="Quantity" value={trade.quantity.toFixed(4)} mono />
          <DetailRow label="Notional Value" value={formatUsd(trade.notional_value)} mono />
          <DetailRow label="Margin Used" value={formatUsd(trade.margin_used)} mono />
          <DetailRow label="Leverage" value={`${trade.leverage}x`} mono />
          <DetailRow label="Fees" value={formatUsd(trade.fees)} mono />
          {trade.fill_type && (
            <DetailRow label="Fill Type" value={trade.fill_type} />
          )}
          <DetailRow label="Entry Time" value={formatTimestamp(trade.entry_time)} />
          {trade.exit_time && (
            <DetailRow label="Exit Time" value={formatTimestamp(trade.exit_time)} last />
          )}
          {!trade.exit_time && <DetailRow label="Status" value={trade.status} last />}
        </div>

        {/* Message */}
        {trade.message && (
          <div
            className="rounded-xl border p-3"
            style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
          >
            <span className="text-[10px] uppercase tracking-wider" style={{ color: "#787b86" }}>
              Signal Message
            </span>
            <p className="mt-1 text-xs" style={{ color: "#d1d4dc" }}>
              {trade.message}
            </p>
          </div>
        )}
      </div>
    </BottomSheet>
  );
});

function DetailRow({
  label,
  value,
  mono = false,
  last = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  last?: boolean;
}) {
  return (
    <div
      className={`flex min-h-[44px] items-center justify-between px-4 py-2.5 ${last ? "" : "border-b"}`}
      style={{ borderColor: "rgba(42,46,57,0.3)" }}
    >
      <span className="text-xs" style={{ color: "#787b86" }}>{label}</span>
      <span
        className={`text-xs tabular-nums ${mono ? "font-mono" : ""}`}
        style={{ color: "#d1d4dc" }}
      >
        {value}
      </span>
    </div>
  );
}
