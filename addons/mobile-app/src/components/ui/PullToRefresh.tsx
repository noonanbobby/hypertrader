"use client";

import { useCallback, useRef, useState } from "react";
import { useHaptic } from "@/hooks/useHaptic";

interface PullToRefreshProps {
  onRefresh: () => Promise<void>;
  children: React.ReactNode;
  className?: string;
}

const THRESHOLD = 80;
const MAX_PULL = 120;

export function PullToRefresh({ onRefresh, children, className = "" }: PullToRefreshProps) {
  const haptic = useHaptic();
  const containerRef = useRef<HTMLDivElement>(null);
  const [pullDistance, setPullDistance] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const touchRef = useRef({ startY: 0, pulling: false, triggered: false });

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const container = containerRef.current;
    if (!container || container.scrollTop > 0 || refreshing) return;
    touchRef.current.startY = e.touches[0].clientY;
    touchRef.current.pulling = true;
    touchRef.current.triggered = false;
  }, [refreshing]);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!touchRef.current.pulling || refreshing) return;
    const deltaY = e.touches[0].clientY - touchRef.current.startY;
    if (deltaY <= 0) {
      setPullDistance(0);
      return;
    }
    // Rubber band effect
    const distance = Math.min(deltaY * 0.5, MAX_PULL);
    setPullDistance(distance);

    if (distance >= THRESHOLD && !touchRef.current.triggered) {
      touchRef.current.triggered = true;
      haptic("medium");
    }
  }, [refreshing, haptic]);

  const handleTouchEnd = useCallback(async () => {
    if (!touchRef.current.pulling) return;
    touchRef.current.pulling = false;

    if (pullDistance >= THRESHOLD) {
      setRefreshing(true);
      setPullDistance(THRESHOLD * 0.6);
      try {
        await onRefresh();
      } finally {
        setRefreshing(false);
        setPullDistance(0);
      }
    } else {
      setPullDistance(0);
    }
  }, [pullDistance, onRefresh]);

  const progress = Math.min(pullDistance / THRESHOLD, 1);
  const rotation = progress * 360;

  return (
    <div
      ref={containerRef}
      className={`relative overflow-y-auto overscroll-contain ${className}`}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      {/* Pull indicator */}
      <div
        className="pointer-events-none absolute left-0 right-0 top-0 z-10 flex justify-center overflow-hidden"
        style={{
          height: `${pullDistance}px`,
          transition: touchRef.current.pulling ? "none" : "height 300ms ease-out",
        }}
      >
        <div
          className="mt-3"
          style={{
            opacity: progress,
            transform: `rotate(${rotation}deg)`,
            transition: touchRef.current.pulling ? "none" : "all 300ms ease-out",
          }}
        >
          {refreshing ? (
            <div
              className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
              style={{ borderColor: "#2962ff", borderTopColor: "transparent" }}
            />
          ) : (
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#787b86"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="1 4 1 10 7 10" />
              <path d="M3.51 15a9 9 0 102.13-9.36L1 10" />
            </svg>
          )}
        </div>
      </div>

      {/* Content with transform */}
      <div
        style={{
          transform: `translateY(${pullDistance}px)`,
          transition: touchRef.current.pulling ? "none" : "transform 300ms ease-out",
        }}
      >
        {children}
      </div>
    </div>
  );
}
