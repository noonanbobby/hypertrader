"use client";

import useSWR from "swr";
import {
  fetchPortfolio,
  fetchLivePositions,
  fetchLiveFills,
  fetchTrades,
  fetchAnalytics,
  fetchSettings,
  fetchAssetConfigs,
  fetchStatus,
  fetchDashboard,
} from "@/lib/api";
import { REFRESH_INTERVALS } from "@/lib/constants";

export function usePortfolio() {
  return useSWR("portfolio", fetchPortfolio, {
    refreshInterval: REFRESH_INTERVALS.portfolio,
    revalidateOnFocus: true,
    errorRetryCount: 3,
    dedupingInterval: 2000,
  });
}

export function useLivePositions() {
  return useSWR("live-positions", fetchLivePositions, {
    refreshInterval: REFRESH_INTERVALS.positions,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}

export function useLiveFills() {
  return useSWR("live-fills", fetchLiveFills, {
    refreshInterval: REFRESH_INTERVALS.trades,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}

export function useTrades(params?: {
  limit?: number;
  offset?: number;
  side?: string;
  status?: string;
}) {
  const key = params
    ? `trades-${JSON.stringify(params)}`
    : "trades";
  return useSWR(key, () => fetchTrades(params), {
    refreshInterval: REFRESH_INTERVALS.trades,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}

export function useAnalytics() {
  return useSWR("analytics", fetchAnalytics, {
    refreshInterval: REFRESH_INTERVALS.analytics,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}

export function useAssetConfigs() {
  return useSWR("asset-configs", fetchAssetConfigs, {
    refreshInterval: 0,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}

export function useSettings() {
  return useSWR("settings", fetchSettings, {
    refreshInterval: 0,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}

export function useSystemStatus() {
  return useSWR("system-status", fetchStatus, {
    refreshInterval: REFRESH_INTERVALS.status,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}

export function useDashboard() {
  return useSWR("dashboard", fetchDashboard, {
    refreshInterval: REFRESH_INTERVALS.portfolio,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  });
}
