"use client";

import { memo } from "react";
import type { HLFill } from "@/types";
import { formatPrice, formatPnl, formatTimeAgo, pnlColor } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";

interface ActivityFeedProps {
  fills: HLFill[] | undefined;
  isLoading: boolean;
}

export const ActivityFeed = memo(function ActivityFeed({
  fills,
  isLoading,
}: ActivityFeedProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 rounded-xl border p-3"
            style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
          >
            <Skeleton width={36} height={36} rounded />
            <div className="flex-1">
              <Skeleton height={12} width="50%" className="mb-1.5" />
              <Skeleton height={10} width="70%" />
            </div>
            <Skeleton height={16} width={60} />
          </div>
        ))}
      </div>
    );
  }

  if (!fills || fills.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border py-8" style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#787b86" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
        <p className="text-xs" style={{ color: "#787b86" }}>No recent activity</p>
      </div>
    );
  }

  const recent = fills.slice(0, 10);

  return (
    <div className="flex flex-col gap-2">
      {recent.map((fill, i) => {
        const isBuy = fill.side.toLowerCase() === "b" || fill.side.toLowerCase() === "buy";
        return (
          <div
            key={`${fill.time}-${fill.price}-${i}`}
            className="flex items-center gap-3 rounded-xl border p-3 animate-fade-in"
            style={{
              backgroundColor: "#1e222d",
              borderColor: "rgba(42,46,57,0.6)",
              animationDelay: `${i * 50}ms`,
            }}
          >
            {/* Icon */}
            <div
              className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full"
              style={{
                backgroundColor: isBuy ? "rgba(38,166,154,0.15)" : "rgba(239,83,80,0.15)",
              }}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke={isBuy ? "#26a69a" : "#ef5350"}
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {isBuy ? (
                  <polyline points="17 11 12 6 7 11" />
                ) : (
                  <polyline points="7 13 12 18 17 13" />
                )}
                <line x1="12" y1={isBuy ? "6" : "18"} x2="12" y2={isBuy ? "18" : "6"} />
              </svg>
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-xs font-semibold" style={{ color: "#d1d4dc" }}>
                  {fill.symbol}
                </span>
                <Badge variant={isBuy ? "buy" : "sell"}>
                  {isBuy ? "BUY" : "SELL"}
                </Badge>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="font-mono text-[10px] tabular-nums" style={{ color: "#787b86" }}>
                  {formatPrice(fill.price)} × {fill.size.toFixed(4)}
                </span>
                <span className="text-[10px]" style={{ color: "#787b86" }}>
                  {formatTimeAgo(fill.time)}
                </span>
              </div>
            </div>

            {/* P&L */}
            {fill.closed_pnl !== 0 && (
              <span
                className="font-mono text-xs font-semibold tabular-nums flex-shrink-0"
                style={{ color: pnlColor(fill.closed_pnl) }}
              >
                {formatPnl(fill.closed_pnl)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
});
