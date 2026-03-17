import { API_BASE_URL } from "./constants";
import type {
  DashboardStats,
  Strategy,
  Trade,
  Position,
  Analytics,
  AppSettings,
  AppSettingsUpdate,
  AssetConfig,
  AssetConfigUpdate,
  HLPortfolio,
  HLPosition,
  HLFill,
  HLStatus,
  PositionTracking,
  LiveTrade,
  PositionActionResponse,
} from "@/types";

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "API Error");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Dashboard
export const getDashboard = () => fetchApi<DashboardStats>("/api/dashboard");

// Strategies
export const getStrategies = () => fetchApi<Strategy[]>("/api/strategies");
export const getStrategy = (id: number) =>
  fetchApi<Strategy>(`/api/strategies/${id}`);
export const createStrategy = (data: Partial<Strategy>) =>
  fetchApi<Strategy>("/api/strategies", {
    method: "POST",
    body: JSON.stringify(data),
  });
export const updateStrategy = (id: number, data: Partial<Strategy>) =>
  fetchApi<Strategy>(`/api/strategies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
export const deleteStrategy = (id: number) =>
  fetchApi<void>(`/api/strategies/${id}`, { method: "DELETE" });

// Trades
export const getTrades = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return fetchApi<Trade[]>(`/api/trades${qs}`);
};

// Close trade
export const closeTrade = (tradeId: number) =>
  fetchApi<{ success: boolean; message: string; trade_id: number | null }>(
    `/api/trades/${tradeId}/close`,
    { method: "POST" }
  );

// Positions
export const getPositions = (strategyId?: number) => {
  const qs = strategyId ? `?strategy_id=${strategyId}` : "";
  return fetchApi<Position[]>(`/api/positions${qs}`);
};

// Analytics
export const getAnalytics = (strategyId?: number) => {
  const qs = strategyId ? `?strategy_id=${strategyId}` : "";
  return fetchApi<Analytics>(`/api/analytics${qs}`);
};

// Settings
export const getSettings = () => fetchApi<AppSettings>("/api/settings");
export const updateSettings = (data: AppSettingsUpdate) =>
  fetchApi<AppSettings>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

// Telegram
export const testTelegram = () =>
  fetchApi<{ success: boolean; message: string }>("/api/settings/test-telegram", {
    method: "POST",
  });

// Health
export const getHealth = () =>
  fetchApi<{ status: string; mode: string; version: string }>("/api/health");

// Assets
export const getAssets = () => fetchApi<AssetConfig[]>("/api/assets");
export const updateAsset = (coin: string, data: AssetConfigUpdate) =>
  fetchApi<AssetConfig>(`/api/assets/${encodeURIComponent(coin)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

// Live (Hyperliquid)
export const getLivePortfolio = () => fetchApi<HLPortfolio>("/api/live/portfolio");
export const getLivePositions = () => fetchApi<HLPosition[]>("/api/live/positions");
export const getLiveFills = () => fetchApi<HLFill[]>("/api/live/fills");
export const getLiveStatus = () => fetchApi<HLStatus>("/api/live/status");

export const closeLivePosition = (symbol: string) =>
  fetchApi<{ success: boolean; message: string }>(`/api/live/positions/${symbol}/close`, {
    method: "POST",
  });

// Position Tracking
export const getPositionTracking = () =>
  fetchApi<PositionTracking[]>("/api/positions");
export const openPosition = (coin: string, data: { direction: string; amount_usd: number }) =>
  fetchApi<PositionActionResponse>(`/api/positions/${coin}/open`, {
    method: "POST",
    body: JSON.stringify(data),
  });
export const addToPosition = (coin: string, add_pct: number) =>
  fetchApi<PositionActionResponse>(`/api/positions/${coin}/add`, {
    method: "POST",
    body: JSON.stringify({ add_pct }),
  });
export const reducePosition = (coin: string, reduce_pct: number) =>
  fetchApi<PositionActionResponse>(`/api/positions/${coin}/reduce`, {
    method: "POST",
    body: JSON.stringify({ reduce_pct }),
  });
export const closeTrackedPosition = (coin: string) =>
  fetchApi<PositionActionResponse>(`/api/positions/${coin}/close`, {
    method: "POST",
  });
export const closeAllPositions = () =>
  fetchApi<PositionActionResponse>("/api/positions/close-all", {
    method: "POST",
  });

// Live Trades
export const getLiveTrades = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return fetchApi<LiveTrade[]>(`/api/trades${qs}`);
};

// SWR fetcher
export const fetcher = (url: string) =>
  fetch(`${API_BASE_URL}${url}`).then((r) => r.json());
