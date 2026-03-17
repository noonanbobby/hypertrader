export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "";
export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  (typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`
    : "ws://localhost:8000/ws");

export const NAV_ITEMS = [
  { label: "Dashboard", href: "/", icon: "LayoutDashboard" },
  { label: "Strategies", href: "/strategies", icon: "Target" },
  { label: "Trades", href: "/trades", icon: "ArrowLeftRight" },
  { label: "Analytics", href: "/analytics", icon: "BarChart3" },
  { label: "Settings", href: "/settings", icon: "Settings" },
] as const;
