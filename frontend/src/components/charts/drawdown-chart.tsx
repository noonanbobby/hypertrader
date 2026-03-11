"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { PnlDataPoint } from "@/types";
import { TrendingDown } from "lucide-react";

interface DrawdownChartProps {
  data: PnlDataPoint[];
}

export function DrawdownChart({ data }: DrawdownChartProps) {
  const chartData = data.map((d) => ({
    date: new Date(d.timestamp).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    drawdown: -d.drawdown,
  }));

  return (
    <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] overflow-hidden">
      <div className="flex items-center gap-2 px-5 pt-5 pb-3">
        <TrendingDown className="h-4 w-4 text-red-400/60" />
        <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
          Drawdown
        </span>
      </div>
      {chartData.length === 0 ? (
        <div className="h-[200px] flex items-center justify-center text-white/20 text-sm">
          No data yet
        </div>
      ) : (
        <div className="px-3 pb-3">
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={chartData}>
              <XAxis
                dataKey="date"
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
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                contentStyle={{
                  background: "rgba(12, 16, 33, 0.95)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: "12px",
                  color: "#f1f5f9",
                  fontSize: "11px",
                  backdropFilter: "blur(20px)",
                }}
              />
              <Area
                type="monotone"
                dataKey="drawdown"
                stroke="#ef4444"
                fill="rgba(239,68,68,0.1)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
