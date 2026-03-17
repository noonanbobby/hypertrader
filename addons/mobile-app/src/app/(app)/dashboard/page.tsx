"use client";

import { useCallback } from "react";
import { usePortfolio, useLivePositions, useLiveFills } from "@/hooks/useApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSoundEvents } from "@/hooks/useSoundEvents";
import { PullToRefresh } from "@/components/ui/PullToRefresh";
import { AccountCards } from "@/components/dashboard/AccountCards";
import { PositionCard } from "@/components/dashboard/PositionCard";
import { KillSwitch } from "@/components/dashboard/KillSwitch";
import { ActivityFeed } from "@/components/dashboard/ActivityFeed";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusDot } from "@/components/ui/Badge";
import { closePosition } from "@/lib/api";
import type { WsEvent, PnlUpdate } from "@/types";

export default function DashboardPage() {
  const {
    data: portfolio,
    isLoading: portfolioLoading,
    mutate: refreshPortfolio,
  } = usePortfolio();
  const {
    data: positions,
    isLoading: positionsLoading,
    mutate: refreshPositions,
  } = useLivePositions();
  const {
    data: fills,
    isLoading: fillsLoading,
    mutate: refreshFills,
  } = useLiveFills();

  // Sound events
  const { handleWsEvent: handleSoundEvent, playEvent } = useSoundEvents();

  // WebSocket for real-time updates
  const handleWsMessage = useCallback(
    (event: WsEvent) => {
      // Trigger sound/haptic for trade events
      handleSoundEvent(event);

      if (event.type === "pnl_update") {
        refreshPositions();
        refreshPortfolio();
      } else if (event.type === "trade_fill") {
        refreshPositions();
        refreshFills();
        refreshPortfolio();
      } else if (event.type === "position_update") {
        refreshPositions();
        refreshPortfolio();
      }
    },
    [handleSoundEvent, refreshPositions, refreshPortfolio, refreshFills],
  );

  const { connected } = useWebSocket({ onMessage: handleWsMessage });

  const handleRefresh = useCallback(async () => {
    await Promise.all([refreshPortfolio(), refreshPositions(), refreshFills()]);
  }, [refreshPortfolio, refreshPositions, refreshFills]);

  const handleCloseAll = useCallback(async () => {
    if (!positions || positions.length === 0) return;
    playEvent("sell_open");
    const closePromises = positions.map((p) => closePosition(p.symbol));
    await Promise.allSettled(closePromises);
    await handleRefresh();
  }, [positions, playEvent, handleRefresh]);

  const handlePositionClosed = useCallback(() => {
    refreshPositions();
    refreshPortfolio();
    refreshFills();
  }, [refreshPositions, refreshPortfolio, refreshFills]);

  const hasPositions = (positions?.length ?? 0) > 0;

  return (
    <PullToRefresh onRefresh={handleRefresh} className="min-h-full">
      <div className="flex flex-col gap-4 pb-4 safe-top">
        {/* Header */}
        <div className="flex items-center justify-between px-4 pt-4">
          <h1 className="text-lg font-semibold" style={{ color: "#d1d4dc" }}>
            Dashboard
          </h1>
          <StatusDot
            status={connected ? "ok" : portfolio ? "ok" : "down"}
            label={connected ? "Live" : portfolio ? "Polling" : "Disconnected"}
          />
        </div>

        {/* Account cards */}
        <AccountCards portfolio={portfolio} isLoading={portfolioLoading} />

        {/* Positions */}
        <div className="px-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium" style={{ color: "#787b86" }}>
              Open Positions
            </h2>
            {positions && (
              <span className="text-xs font-mono tabular-nums" style={{ color: "#787b86" }}>
                {positions.length}
              </span>
            )}
          </div>

          {positionsLoading ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 2 }, (_, i) => (
                <div
                  key={i}
                  className="rounded-xl border p-3"
                  style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Skeleton width={50} height={14} />
                    <Skeleton width={40} height={16} />
                    <Skeleton width={24} height={16} />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <Skeleton height={12} width="80%" />
                    <Skeleton height={12} width="60%" />
                    <Skeleton height={12} width="70%" />
                    <Skeleton height={12} width="50%" />
                  </div>
                </div>
              ))}
            </div>
          ) : positions && positions.length > 0 ? (
            <div className="flex flex-col gap-3">
              {positions.map((pos) => (
                <PositionCard
                  key={`${pos.symbol}-${pos.side}`}
                  position={pos}
                  onClosed={handlePositionClosed}
                />
              ))}
            </div>
          ) : (
            <div
              className="flex flex-col items-center justify-center gap-2 rounded-xl border py-8"
              style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
            >
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#787b86" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
                <path d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16" />
              </svg>
              <p className="text-xs" style={{ color: "#787b86" }}>No open positions</p>
            </div>
          )}
        </div>

        {/* Activity feed */}
        <div className="px-4">
          <h2 className="mb-3 text-sm font-medium" style={{ color: "#787b86" }}>
            Recent Activity
          </h2>
          <ActivityFeed fills={fills} isLoading={fillsLoading} />
        </div>
      </div>

      {/* Kill switch FAB */}
      <KillSwitch
        onConfirm={handleCloseAll}
        hasPositions={hasPositions}
      />
    </PullToRefresh>
  );
}
