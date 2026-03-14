"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { DashboardStats, Strategy, Trade, Position, Analytics, AppSettings, SystemStatus, HLPortfolio, HLPosition, HLFill, HLStatus } from "@/types";

export function useDashboard() {
  return useSWR<DashboardStats>("/api/dashboard", fetcher, {
    refreshInterval: 5000,
  });
}

export function useStrategies() {
  return useSWR<Strategy[]>("/api/strategies", fetcher, {
    refreshInterval: 15000,
  });
}

export function useTrades(params?: Record<string, string>) {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return useSWR<Trade[]>(`/api/trades${qs}`, fetcher, {
    refreshInterval: 10000,
  });
}

export function usePositions(strategyId?: number) {
  const qs = strategyId ? `?strategy_id=${strategyId}` : "";
  return useSWR<Position[]>(`/api/positions${qs}`, fetcher, {
    refreshInterval: 5000,
  });
}

export function useAnalytics(strategyId?: number) {
  const qs = strategyId ? `?strategy_id=${strategyId}` : "";
  return useSWR<Analytics>(`/api/analytics${qs}`, fetcher, {
    refreshInterval: 30000,
  });
}

export function useSystemStatus() {
  return useSWR<SystemStatus>("/api/status", fetcher, {
    refreshInterval: 10000,
  });
}

export function useSettings() {
  return useSWR<AppSettings>("/api/settings", fetcher, {
    refreshInterval: 0,
    revalidateOnFocus: true,
  });
}

// --- Hyperliquid Live ---
export function useLivePortfolio(enabled = true) {
  return useSWR<HLPortfolio>(enabled ? "/api/live/portfolio" : null, fetcher, {
    refreshInterval: 5000,
  });
}

export function useLivePositions(enabled = true) {
  return useSWR<HLPosition[]>(enabled ? "/api/live/positions" : null, fetcher, {
    refreshInterval: 5000,
  });
}

export function useLiveFills(enabled = true) {
  return useSWR<HLFill[]>(enabled ? "/api/live/fills" : null, fetcher, {
    refreshInterval: 10000,
  });
}

export function useLiveStatus() {
  return useSWR<HLStatus>("/api/live/status", fetcher, {
    refreshInterval: 30000,
  });
}
