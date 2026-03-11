"use client";

import { formatPnl } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus, Sun, Calendar, CalendarDays } from "lucide-react";

interface PnlCardsProps {
  daily: number;
  weekly: number;
  monthly: number;
}

function PnlCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
}) {
  const positive = value >= 0;
  return (
    <div className="gradient-border rounded-2xl p-5 backdrop-blur-xl bg-white/[0.02]">
      <div className="flex items-center gap-2 mb-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/[0.04]">
          <Icon className="h-3.5 w-3.5 text-white/40" />
        </div>
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/30">
          {label}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {value > 0 ? (
          <TrendingUp className="h-4 w-4 text-emerald-400" />
        ) : value < 0 ? (
          <TrendingDown className="h-4 w-4 text-red-400" />
        ) : (
          <Minus className="h-4 w-4 text-white/30" />
        )}
        <span
          className={`text-xl font-bold ${
            positive ? "text-emerald-400" : "text-red-400"
          }`}
        >
          {formatPnl(value)}
        </span>
      </div>
    </div>
  );
}

export function PnlCards({ daily, weekly, monthly }: PnlCardsProps) {
  return (
    <>
      <PnlCard label="Today" value={daily} icon={Sun} />
      <PnlCard label="This Week" value={weekly} icon={Calendar} />
      <PnlCard label="This Month" value={monthly} icon={CalendarDays} />
    </>
  );
}
