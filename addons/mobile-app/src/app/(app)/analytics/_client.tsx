"use client";

import { useCallback } from "react";
import dynamicImport from "next/dynamic";
import { useAnalytics } from "@/hooks/useApi";
import { PullToRefresh } from "@/components/ui/PullToRefresh";
import { MetricCards } from "@/components/analytics/MetricCards";
import { SkeletonChart } from "@/components/ui/Skeleton";

const EquityCurve = dynamicImport(
  () => import("@/components/analytics/PerformanceCharts").then((m) => ({ default: m.EquityCurve })),
  { ssr: false, loading: () => <SkeletonChart /> },
);
const DrawdownChart = dynamicImport(
  () => import("@/components/analytics/PerformanceCharts").then((m) => ({ default: m.DrawdownChart })),
  { ssr: false, loading: () => <SkeletonChart /> },
);
const DailyPnlChart = dynamicImport(
  () => import("@/components/analytics/PerformanceCharts").then((m) => ({ default: m.DailyPnlChart })),
  { ssr: false, loading: () => <SkeletonChart /> },
);

export default function AnalyticsPage() {
  const { data: analytics, isLoading, error, mutate } = useAnalytics();

  const handleRefresh = useCallback(async () => {
    await mutate();
  }, [mutate]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-8" style={{ minHeight: "60vh" }}>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#ef5350" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <p className="text-sm" style={{ color: "#d1d4dc" }}>Failed to load analytics</p>
        <button
          onClick={() => mutate()}
          className="rounded-lg px-6 py-2.5 text-sm font-medium transition-default active:scale-95"
          style={{ backgroundColor: "#2962ff", color: "#fff" }}
        >
          Retry
        </button>
      </div>
    );
  }

  const hasEquityData = analytics && analytics.equity_curve.length > 0;

  return (
    <PullToRefresh onRefresh={handleRefresh} className="min-h-full">
      <div className="flex flex-col gap-4 pb-4 safe-top">
        <div className="px-4 pt-4">
          <h1 className="text-lg font-semibold" style={{ color: "#d1d4dc" }}>
            Analytics
          </h1>
        </div>

        {/* Metric cards strip */}
        <MetricCards analytics={analytics} isLoading={isLoading} />

        {/* Charts */}
        <div className="flex flex-col gap-4 px-4">
          {isLoading ? (
            <>
              <SkeletonChart />
              <SkeletonChart />
              <SkeletonChart />
            </>
          ) : hasEquityData ? (
            <>
              <EquityCurve data={analytics.equity_curve} />
              <DrawdownChart data={analytics.equity_curve} />
              <DailyPnlChart data={analytics.equity_curve} />
            </>
          ) : (
            <div
              className="flex flex-col items-center justify-center gap-4 rounded-xl border py-12 px-6"
              style={{ backgroundColor: "#12131a", borderColor: "rgba(42,46,57,0.5)" }}
            >
              <div style={{ position: "relative", width: "48px", height: "48px" }}>
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                  <circle cx="24" cy="24" r="20" stroke="rgba(255,255,255,0.06)" strokeWidth="3" />
                  <circle cx="24" cy="24" r="20" stroke="#2962ff" strokeWidth="3" strokeLinecap="round"
                    strokeDasharray="126" strokeDashoffset={126 - (analytics ? Math.min(analytics.total_trades, 10) / 10 * 126 : 0)}
                    style={{ transition: "stroke-dashoffset 1s", transform: "rotate(-90deg)", transformOrigin: "center" }} />
                </svg>
                <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "12px", fontWeight: 600, color: "#2962ff", fontFamily: "'JetBrains Mono', monospace" }}>
                  {analytics?.total_trades ?? 0}
                </span>
              </div>
              <div className="text-center">
                <p className="text-sm font-medium" style={{ color: "#e0e0e0" }}>
                  Collecting Data...
                </p>
                <p className="text-xs mt-1" style={{ color: "#787b86" }}>
                  {analytics?.total_trades ?? 0} trades recorded. Analytics charts populate as equity snapshots accumulate (hourly).
                </p>
              </div>
              <div className="flex gap-3 mt-2">
                <div className="flex items-center gap-1.5">
                  <div style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#00e676" }} />
                  <span className="text-[10px]" style={{ color: "#787b86" }}>Snapshots: hourly</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#2962ff" }} />
                  <span className="text-[10px]" style={{ color: "#787b86" }}>Trades: live</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </PullToRefresh>
  );
}
