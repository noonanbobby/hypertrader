"use client";

import { formatCurrency } from "@/lib/utils";
import { CalendarDays } from "lucide-react";

interface PnlCalendarProps {
  monthlyReturns: Record<string, number>;
}

export function PnlCalendar({ monthlyReturns }: PnlCalendarProps) {
  const entries = Object.entries(monthlyReturns).sort(([a], [b]) =>
    a.localeCompare(b)
  );

  const getColor = (val: number) => {
    if (val > 500) return "bg-emerald-500/20 border-emerald-500/20";
    if (val > 100) return "bg-emerald-500/10 border-emerald-500/10";
    if (val > 0) return "bg-emerald-500/5 border-emerald-500/5";
    if (val > -100) return "bg-red-500/5 border-red-500/5";
    if (val > -500) return "bg-red-500/10 border-red-500/10";
    return "bg-red-500/20 border-red-500/20";
  };

  return (
    <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] overflow-hidden">
      <div className="flex items-center gap-2 px-5 pt-5 pb-4">
        <CalendarDays className="h-4 w-4 text-amber-400/60" />
        <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
          Monthly Returns
        </span>
      </div>
      {entries.length === 0 ? (
        <div className="text-center py-8 text-white/20 text-sm pb-5">
          No monthly data yet
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-2 px-5 pb-5">
          {entries.map(([month, pnl]) => (
            <div
              key={month}
              className={`rounded-xl p-3 text-center border ${getColor(pnl)}`}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wider text-white/30">{month}</p>
              <p
                className={`text-sm font-bold mt-1 ${
                  pnl >= 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {formatCurrency(pnl)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
