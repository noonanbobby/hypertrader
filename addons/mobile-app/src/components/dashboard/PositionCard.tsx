"use client";

import { memo, useCallback, useRef, useState } from "react";
import type { HLPosition } from "@/types";
import { formatPrice, formatPnl, formatPercent, formatUsd, pnlColor } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { useHaptic } from "@/hooks/useHaptic";
import { closePosition } from "@/lib/api";
import { ASSET_COLORS } from "@/lib/constants";

interface PositionCardProps {
  position: HLPosition;
  onClosed?: () => void;
}

export const PositionCard = memo(function PositionCard({
  position,
  onClosed,
}: PositionCardProps) {
  const haptic = useHaptic();
  const [swipeX, setSwipeX] = useState(0);
  const [closing, setClosing] = useState(false);
  const touchRef = useRef({ startX: 0, dragging: false });
  const closeThreshold = -80;

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchRef.current.startX = e.touches[0].clientX;
    touchRef.current.dragging = true;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!touchRef.current.dragging) return;
    const delta = e.touches[0].clientX - touchRef.current.startX;
    // Only allow left swipe
    if (delta < 0) {
      setSwipeX(Math.max(delta, -120));
    } else {
      setSwipeX(0);
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    touchRef.current.dragging = false;
    if (swipeX < closeThreshold) {
      setSwipeX(-120);
      haptic("medium");
    } else {
      setSwipeX(0);
    }
  }, [swipeX, haptic]);

  const handleClose = useCallback(async () => {
    setClosing(true);
    haptic("heavy");
    try {
      await closePosition(position.symbol);
      onClosed?.();
    } catch {
      setSwipeX(0);
    } finally {
      setClosing(false);
    }
  }, [position.symbol, onClosed, haptic]);

  const resetSwipe = useCallback(() => {
    setSwipeX(0);
  }, []);

  const isLong = position.side.toLowerCase() === "long" || position.side.toLowerCase() === "a";
  const pnlPct = position.entry_price > 0
    ? ((position.mark_price - position.entry_price) / position.entry_price) * 100 * (isLong ? 1 : -1)
    : 0;

  return (
    <div className="relative overflow-hidden rounded-xl" style={{ backgroundColor: "#1e222d" }}>
      {/* Close button behind card */}
      <div
        className="absolute right-0 top-0 bottom-0 flex items-center justify-center"
        style={{
          width: "120px",
          backgroundColor: "#ef5350",
        }}
      >
        <button
          onClick={handleClose}
          disabled={closing}
          className="flex h-full w-full items-center justify-center text-sm font-semibold text-white active:opacity-80"
          aria-label={`Close ${position.symbol} position`}
        >
          {closing ? (
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
          ) : (
            "Close"
          )}
        </button>
      </div>

      {/* Card content */}
      <div
        className="relative border p-3"
        style={{
          backgroundColor: "#1e222d",
          borderColor: "rgba(42,46,57,0.6)",
          borderRadius: "12px",
          transform: `translateX(${swipeX}px)`,
          transition: touchRef.current.dragging ? "none" : "transform 300ms ease-out",
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onClick={swipeX < 0 ? resetSwipe : undefined}
      >
        {/* Top row: symbol + side badge + leverage */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold" style={{ color: "#d1d4dc" }}>
              {position.symbol}
            </span>
            <Badge variant={isLong ? "long" : "short"}>
              {isLong ? "LONG" : "SHORT"}
            </Badge>
            <Badge variant="info" size="sm">
              {position.leverage}x
            </Badge>
          </div>
          <span
            className="font-mono text-sm font-semibold tabular-nums"
            style={{ color: pnlColor(position.unrealized_pnl) }}
          >
            {formatPnl(position.unrealized_pnl)}
          </span>
        </div>

        {/* Data grid */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
          <DataRow label="Entry" value={formatPrice(position.entry_price)} />
          <DataRow label="Mark" value={formatPrice(position.mark_price)} />
          <DataRow label="Size" value={position.size.toFixed(4)} />
          <DataRow
            label="P&L %"
            value={formatPercent(pnlPct)}
            valueColor={pnlColor(pnlPct)}
          />
          <DataRow label="Notional" value={formatUsd(position.notional)} />
          <DataRow label="Margin" value={formatUsd(position.margin_used)} />
        </div>

        {/* Swipe hint */}
        {swipeX === 0 && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2 opacity-20">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#787b86" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </div>
        )}
      </div>
    </div>
  );
});

function DataRow({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px]" style={{ color: "#787b86" }}>{label}</span>
      <span
        className="font-mono text-xs tabular-nums"
        style={{ color: valueColor ?? "#d1d4dc" }}
      >
        {value}
      </span>
    </div>
  );
}
