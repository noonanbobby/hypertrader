export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    // Server-side: always hit backend directly
    return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  }
  const hostname = window.location.hostname;
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    // Local dev: hit backend directly
    return "http://localhost:8000";
  }
  // Remote access (Tailscale): use same-origin proxy to avoid mixed content
  // The Next.js API route at /api/[...path] proxies to localhost:8000
  return "";
}

export function getWsUrl(): string {
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";
  }
  const hostname = window.location.hostname;
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return "ws://localhost:8000/ws";
  }
  // Remote access: WebSocket not available (no wss:// on backend port 8000)
  // SWR polling handles data refresh instead
  return "";
}

// Backward-compatible constants (evaluated at module load on client)
export const API_BASE_URL = typeof window !== "undefined" ? getApiBaseUrl() : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
export const WS_URL = typeof window !== "undefined" ? getWsUrl() : (process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws");
export const HL_API_URL =
  process.env.NEXT_PUBLIC_HL_API_URL ?? "https://api.hyperliquid.xyz/info";

export const COLORS = {
  bgPrimary: "#0a0a0f",
  bgPanel: "#12131a",
  border: "rgba(42,46,57,0.5)",
  borderStrong: "rgba(42,46,57,0.6)",
  textPrimary: "#e0e0e0",
  textSecondary: "#787b86",
  bullish: "#00e676",
  bearish: "#ff1744",
  bullishBright: "#00e676",
  bearishBright: "#ff1744",
  bearishDark: "#b71c1c",
  accentBlue: "#2962ff",
  accentCyan: "#00bcd4",
  accentOrange: "#ff9800",
  macdRsiBlue: "#42a5f5",
} as const;

export const ASSET_COLORS: Record<string, string> = {
  BTC: "#f7931a",
  ETH: "#627eea",
  SOL: "#9945ff",
} as const;

export const TIMEFRAMES = ["5m", "15m", "1H", "4H", "1D"] as const;

export const REFRESH_INTERVALS = {
  price: 5_000,
  portfolio: 10_000,
  positions: 5_000,
  trades: 30_000,
  analytics: 60_000,
  status: 15_000,
} as const;

export const TAB_ITEMS = [
  { key: "chart", label: "Chart", href: "/chart" },
  { key: "dashboard", label: "Dashboard", href: "/dashboard" },
  { key: "trades", label: "Trades", href: "/trades" },
  { key: "analytics", label: "Analytics", href: "/analytics" },
  { key: "settings", label: "Settings", href: "/settings" },
] as const;

export const SUPERTREND_CONFIG = {
  atrPeriod: 10,
  multiplier: 4.0,
  source: "hl2" as const,
} as const;

export const SQUEEZE_CONFIG = {
  bbLength: 20,
  bbMultFactor: 2,
  kcLength: 20,
  kcMultFactor: 1.5,
} as const;

export const MACD_RSI_CONFIG = {
  fastLength: 12,
  slowLength: 26,
  signalLength: 9,
  rsiLength: 14,
} as const;

export const AUTO_LOCK_MS = 5 * 60 * 1000;
export const PIN_LENGTH = 4;
