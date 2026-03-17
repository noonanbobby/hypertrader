import { getApiBaseUrl } from "./constants";
import type {
  AnalyticsResponse,
  AppSettings,
  AssetConfig,
  DashboardStats,
  HealthCheck,
  HLFill,
  HLPortfolio,
  HLPosition,
  SystemStatus,
  Trade,
} from "@/types";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${getApiBaseUrl()}${endpoint}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    throw new ApiError(res.status, `API error: ${res.status} ${res.statusText}`);
  }

  return res.json() as Promise<T>;
}

/* ── Dashboard ── */
export function fetchDashboard(): Promise<DashboardStats> {
  return fetchApi<DashboardStats>("/api/dashboard");
}

/* ── Live Portfolio ── */
export function fetchPortfolio(): Promise<HLPortfolio> {
  return fetchApi<HLPortfolio>("/api/live/portfolio");
}

export function fetchLivePositions(): Promise<HLPosition[]> {
  return fetchApi<HLPosition[]>("/api/live/positions");
}

export function fetchLiveFills(): Promise<HLFill[]> {
  return fetchApi<HLFill[]>("/api/live/fills");
}

/* ── Trades ── */
export function fetchTrades(params?: {
  limit?: number;
  offset?: number;
  side?: string;
  status?: string;
}): Promise<Trade[]> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  if (params?.side) searchParams.set("side", String(params.side));
  if (params?.status) searchParams.set("status", String(params.status));
  const qs = searchParams.toString();
  return fetchApi<Trade[]>(`/api/trades${qs ? `?${qs}` : ""}`);
}

/* ── Analytics ── */
export function fetchAnalytics(): Promise<AnalyticsResponse> {
  return fetchApi<AnalyticsResponse>("/api/analytics");
}

/* ── Assets ── */
export function fetchAssetConfigs(): Promise<AssetConfig[]> {
  return fetchApi<AssetConfig[]>("/api/assets");
}

export function updateAssetConfig(
  coin: string,
  updates: Partial<AssetConfig>,
): Promise<AssetConfig> {
  return fetchApi<AssetConfig>(`/api/assets/${encodeURIComponent(coin)}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

/* ── Settings ── */
export function fetchSettings(): Promise<AppSettings> {
  return fetchApi<AppSettings>("/api/settings");
}

export function updateSettings(
  updates: Partial<AppSettings>,
): Promise<AppSettings> {
  return fetchApi<AppSettings>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

/* ── Status ── */
export function fetchStatus(): Promise<SystemStatus> {
  return fetchApi<SystemStatus>("/api/status");
}

export function fetchHealth(): Promise<HealthCheck> {
  return fetchApi<HealthCheck>("/api/health");
}

/* ── Position Actions ── */
export function closePosition(
  symbol: string,
): Promise<{ success: boolean; message: string }> {
  return fetchApi<{ success: boolean; message: string }>(
    `/api/live/positions/${encodeURIComponent(symbol)}/close`,
    { method: "POST" },
  );
}
