"use client";

import { memo } from "react";
import type { HLPortfolio } from "@/types";
import { formatUsd, formatPnl, pnlColor } from "@/lib/format";
import { Skeleton } from "@/components/ui/Skeleton";

interface AccountCardsProps {
  portfolio: HLPortfolio | undefined;
  isLoading: boolean;
}

interface CardConfig {
  label: string;
  getValue: (p: HLPortfolio) => number;
  format: (v: number) => string;
  colorFn?: (v: number) => string;
  accent?: boolean;
}

const cards: CardConfig[] = [
  {
    label: "Account Value",
    getValue: (p) => p.account_value,
    format: (v) => formatUsd(v),
    accent: true,
  },
  {
    label: "Available Balance",
    getValue: (p) => p.available_balance,
    format: (v) => formatUsd(v),
  },
  {
    label: "Margin Used",
    getValue: (p) => p.total_margin_used,
    format: (v) => formatUsd(v),
  },
  {
    label: "Unrealized P&L",
    getValue: (p) => p.total_unrealized_pnl,
    format: (v) => formatPnl(v),
    colorFn: pnlColor,
  },
  {
    label: "Perps Balance",
    getValue: (p) => p.perps_balance,
    format: (v) => formatUsd(v),
  },
  {
    label: "Spot Balance",
    getValue: (p) => p.spot_balance,
    format: (v) => formatUsd(v),
  },
];

export const AccountCards = memo(function AccountCards({
  portfolio,
  isLoading,
}: AccountCardsProps) {
  const marginPct = portfolio && portfolio.account_value > 0
    ? (portfolio.total_margin_used / portfolio.account_value) * 100
    : 0;
  const marginColor = marginPct > 70 ? "#ff1744" : marginPct > 50 ? "#ff9800" : "#00e676";

  return (
    <div className="flex flex-col gap-3 px-4 pt-0.5">
      {/* Margin bar */}
      {portfolio && (
        <div className="rounded-xl border p-3" style={{ backgroundColor: "#12131a", borderColor: "rgba(42,46,57,0.5)" }}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "#787b86" }}>Margin Usage</span>
            <span className="text-xs font-mono font-semibold tabular-nums" style={{ color: marginColor }}>{marginPct.toFixed(1)}%</span>
          </div>
          <div style={{ height: "4px", borderRadius: "2px", backgroundColor: "rgba(255,255,255,0.06)" }}>
            <div style={{ height: "100%", width: `${Math.min(marginPct, 100)}%`, borderRadius: "2px", backgroundColor: marginColor, transition: "width 0.3s" }} />
          </div>
        </div>
      )}
      <div
        className="flex gap-3 overflow-x-auto pb-1"
        style={{ scrollSnapType: "x mandatory", WebkitOverflowScrolling: "touch" }}
      >
      {cards.map((card) => {
        const value = portfolio ? card.getValue(portfolio) : null;
        const color = value !== null && card.colorFn ? card.colorFn(value) : "#d1d4dc";

        return (
          <div
            key={card.label}
            className="min-w-[155px] flex-shrink-0 rounded-xl border p-3"
            style={{
              backgroundColor: "#1e222d",
              borderColor: card.accent && portfolio
                ? "rgba(41,98,255,0.3)"
                : "rgba(42,46,57,0.6)",
              scrollSnapAlign: "start",
              boxShadow: card.accent ? "0 0 12px rgba(41,98,255,0.08)" : undefined,
            }}
          >
            <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "#787b86" }}>
              {card.label}
            </span>
            {isLoading || value === null ? (
              <Skeleton height={22} width="75%" className="mt-1.5" />
            ) : (
              <p
                className="mt-1 font-mono text-lg font-semibold tabular-nums"
                style={{ color }}
              >
                {card.format(value)}
              </p>
            )}
          </div>
        );
      })}
      </div>
    </div>
  );
});
