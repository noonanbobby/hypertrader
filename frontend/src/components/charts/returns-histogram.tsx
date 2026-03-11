"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { Trade } from "@/types";
import { BarChart3 } from "lucide-react";

interface ReturnsHistogramProps {
  trades: Trade[];
}

export function ReturnsHistogram({ trades }: ReturnsHistogramProps) {
  const closedTrades = trades.filter((t) => t.status === "closed");

  if (closedTrades.length === 0) {
    return (
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] overflow-hidden">
        <div className="flex items-center gap-2 px-5 pt-5 pb-3">
          <BarChart3 className="h-4 w-4 text-purple-400/60" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Returns Distribution
          </span>
        </div>
        <div className="h-[200px] flex items-center justify-center text-white/20 text-sm">
          No closed trades yet
        </div>
      </div>
    );
  }

  const pnls = closedTrades.map((t) => t.realized_pnl);
  const min = Math.min(...pnls);
  const max = Math.max(...pnls);
  const range = max - min || 1;
  const bucketSize = range / 10;

  const buckets: { range: string; count: number; isPositive: boolean }[] = [];
  for (let i = 0; i < 10; i++) {
    const lo = min + i * bucketSize;
    const hi = lo + bucketSize;
    const count = pnls.filter((p) => p >= lo && (i === 9 ? p <= hi : p < hi)).length;
    buckets.push({
      range: `$${lo.toFixed(0)}`,
      count,
      isPositive: lo + bucketSize / 2 >= 0,
    });
  }

  return (
    <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] overflow-hidden">
      <div className="flex items-center gap-2 px-5 pt-5 pb-3">
        <BarChart3 className="h-4 w-4 text-purple-400/60" />
        <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
          Returns Distribution
        </span>
      </div>
      <div className="px-3 pb-3">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={buckets}>
            <XAxis
              dataKey="range"
              stroke="rgba(255,255,255,0.15)"
              fontSize={10}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="rgba(255,255,255,0.15)"
              fontSize={10}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                background: "rgba(12, 16, 33, 0.95)",
                border: "1px solid rgba(255,255,255,0.08)",
                borderRadius: "12px",
                color: "#f1f5f9",
                fontSize: "11px",
              }}
            />
            <Bar dataKey="count" radius={[6, 6, 0, 0]}>
              {buckets.map((b, i) => (
                <Cell
                  key={i}
                  fill={b.isPositive ? "rgba(16,185,129,0.6)" : "rgba(239,68,68,0.6)"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
