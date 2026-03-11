"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { DashboardStats, Strategy, Trade, Position, Analytics } from "@/types";

export function useDashboard() {
  return useSWR<DashboardStats>("/api/dashboard", fetcher, {
    refreshInterval: 10000,
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
