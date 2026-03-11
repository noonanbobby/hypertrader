"use client";

import { useEffect, useRef, useState } from "react";
import { formatCurrency, formatPnl, pnlColor } from "@/lib/utils";
import { Wallet, TrendingUp, TrendingDown } from "lucide-react";

interface PortfolioValueProps {
  totalEquity: number;
  totalPnl: number;
}

export function PortfolioValue({ totalEquity, totalPnl }: PortfolioValueProps) {
  const [displayValue, setDisplayValue] = useState(totalEquity);
  const prevValue = useRef(totalEquity);

  useEffect(() => {
    const start = prevValue.current;
    const end = totalEquity;
    if (start === end) return;
    const duration = 800;
    const startTime = Date.now();

    const animate = () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 4);
      setDisplayValue(start + (end - start) * eased);

      if (progress < 1) {
        requestAnimationFrame(animate);
      } else {
        prevValue.current = end;
      }
    };

    requestAnimationFrame(animate);
  }, [totalEquity]);

  const pnlPositive = totalPnl >= 0;

  return (
    <div className="col-span-2 relative overflow-hidden rounded-2xl p-8">
      {/* Background gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-blue-600/10 via-purple-600/5 to-transparent" />
      <div className="absolute inset-0 gradient-border" />
      <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" />

      <div className="relative z-10">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.06]">
            <Wallet className="h-4 w-4 text-white/50" />
          </div>
          <span className="text-xs font-semibold uppercase tracking-wider text-white/40">
            Portfolio Value
          </span>
        </div>
        <div className="text-5xl font-bold text-white tracking-tight mb-3">
          {formatCurrency(displayValue)}
        </div>
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ${
            pnlPositive
              ? "bg-emerald-500/10 text-emerald-400"
              : "bg-red-500/10 text-red-400"
          }`}>
            {pnlPositive ? (
              <TrendingUp className="h-3.5 w-3.5" />
            ) : (
              <TrendingDown className="h-3.5 w-3.5" />
            )}
            {formatPnl(totalPnl)}
          </div>
          <span className="text-xs text-white/30">all time</span>
        </div>
      </div>
    </div>
  );
}
