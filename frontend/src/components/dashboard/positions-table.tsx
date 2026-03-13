"use client";

import { useEffect, useRef, useState } from "react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency, formatPrice, formatPercent } from "@/lib/utils";
import type { Position } from "@/types";
import { Crosshair } from "lucide-react";

type SubscribeFn = (event: string, handler: (data: Record<string, unknown>) => void) => () => void;

interface PnlOverlay {
  current_price: number;
  unrealized_pnl: number;
  pnl_pct: number;
  notional_value: number;
}

interface PositionsTableProps {
  positions: Position[];
  subscribe?: SubscribeFn;
}

export function PositionsTable({ positions, subscribe }: PositionsTableProps) {
  const [overlay, setOverlay] = useState<Map<number, PnlOverlay>>(new Map());
  const prevPositionsRef = useRef(positions);

  // Clear overlay when SWR delivers fresh positions (SWR remains source of truth)
  useEffect(() => {
    if (positions !== prevPositionsRef.current) {
      prevPositionsRef.current = positions;
      setOverlay(new Map());
    }
  }, [positions]);

  // Subscribe to real-time P&L updates
  useEffect(() => {
    if (!subscribe) return;

    return subscribe("pnl_update", (data) => {
      const updates = data as unknown as (PnlOverlay & { id: number })[];
      if (!Array.isArray(updates)) return;

      setOverlay((prev) => {
        const next = new Map(prev);
        for (const u of updates) {
          next.set(u.id, {
            current_price: u.current_price,
            unrealized_pnl: u.unrealized_pnl,
            pnl_pct: u.pnl_pct,
            notional_value: u.notional_value,
          });
        }
        return next;
      });
    });
  }, [subscribe]);

  if (positions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Crosshair className="h-4 w-4 text-white/30" />
            <CardTitle>Open Positions</CardTitle>
          </div>
        </CardHeader>
        <div className="text-center py-12">
          <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-white/[0.03] mb-4">
            <Crosshair className="h-7 w-7 text-white/10" />
          </div>
          <p className="text-white/30 text-sm">No open positions</p>
          <p className="text-white/15 text-xs mt-1">Waiting for signals...</p>
        </div>
      </Card>
    );
  }

  // Merge WS overlay into positions for rendering
  const merged = positions.map((pos) => {
    const o = overlay.get(pos.id);
    if (!o) return pos;
    return {
      ...pos,
      current_price: o.current_price,
      unrealized_pnl: o.unrealized_pnl,
      pnl_pct: o.pnl_pct,
      notional_value: o.notional_value,
    };
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Crosshair className="h-4 w-4 text-white/30" />
          <CardTitle>Open Positions</CardTitle>
        </div>
        <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-[10px] font-bold text-emerald-400">{positions.length} ACTIVE</span>
        </div>
      </CardHeader>
      <div className="overflow-x-auto -mx-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.04]">
              <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Symbol</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Side</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Lev</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Size</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Entry</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Mark</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Margin</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Unreal. P&L</th>
              <th className="text-right px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Notional</th>
            </tr>
          </thead>
          <tbody>
            {merged.map((pos) => {
              const positive = pos.unrealized_pnl >= 0;
              return (
                <tr
                  key={pos.id}
                  className="border-b border-white/[0.03] table-row-hover"
                >
                  <td className="px-6 py-4">
                    <span className="font-semibold text-white">{pos.symbol}</span>
                    <span className="text-white/20 text-xs ml-1">PERP</span>
                  </td>
                  <td className="px-3 py-4">
                    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                      pos.side === "long"
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        : "bg-red-500/10 text-red-400 border border-red-500/20"
                    }`}>
                      {pos.side}
                    </span>
                  </td>
                  <td className="px-3 py-4">
                    <span className="inline-flex items-center rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-bold">
                      {pos.leverage}x
                    </span>
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/80">
                    {pos.quantity}
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/50">
                    {formatPrice(pos.entry_price)}
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white transition-all duration-300">
                    {formatPrice(pos.current_price)}
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/50">
                    {formatCurrency(pos.margin_used)}
                  </td>
                  <td className="px-3 py-4 text-right transition-all duration-300">
                    <span className={`font-bold ${positive ? "text-emerald-400" : "text-red-400"}`}>
                      {formatCurrency(pos.unrealized_pnl)}
                    </span>
                    <br />
                    <span className={`text-[10px] font-medium ${positive ? "text-emerald-400/60" : "text-red-400/60"}`}>
                      {formatPercent(pos.pnl_pct)}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right font-mono text-white/30 transition-all duration-300">
                    {formatCurrency(pos.notional_value)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
