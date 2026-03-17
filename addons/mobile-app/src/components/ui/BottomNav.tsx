"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { useHaptic } from "@/hooks/useHaptic";
import type { TabKey } from "@/types";

const tabs: { key: TabKey; label: string; href: string }[] = [
  { key: "chart", label: "Chart", href: "/chart" },
  { key: "dashboard", label: "Dashboard", href: "/dashboard" },
  { key: "trades", label: "Trades", href: "/trades" },
  { key: "analytics", label: "Analytics", href: "/analytics" },
  { key: "settings", label: "Settings", href: "/settings" },
];

function ChartIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? "#2962ff" : "#787b86"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 3v18h18" />
      <path d="M7 16l4-8 4 4 5-6" />
    </svg>
  );
}

function DashboardIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? "#2962ff" : "#787b86"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  );
}

function TradesIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? "#2962ff" : "#787b86"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" />
    </svg>
  );
}

function AnalyticsIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? "#2962ff" : "#787b86"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 21H4.6c-.56 0-.84 0-1.054-.109a1 1 0 01-.437-.437C3 20.24 3 19.96 3 19.4V3" />
      <path d="M7 14l4-4 4 4 6-6" />
    </svg>
  );
}

function SettingsIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? "#2962ff" : "#787b86"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12.22 2h-.44a2 2 0 00-2 2v.18a2 2 0 01-1 1.73l-.43.25a2 2 0 01-2 0l-.15-.08a2 2 0 00-2.73.73l-.22.38a2 2 0 00.73 2.73l.15.1a2 2 0 011 1.72v.51a2 2 0 01-1 1.74l-.15.09a2 2 0 00-.73 2.73l.22.38a2 2 0 002.73.73l.15-.08a2 2 0 012 0l.43.25a2 2 0 011 1.73V20a2 2 0 002 2h.44a2 2 0 002-2v-.18a2 2 0 011-1.73l.43-.25a2 2 0 012 0l.15.08a2 2 0 002.73-.73l.22-.39a2 2 0 00-.73-2.73l-.15-.08a2 2 0 01-1-1.74v-.5a2 2 0 011-1.74l.15-.09a2 2 0 00.73-2.73l-.22-.38a2 2 0 00-2.73-.73l-.15.08a2 2 0 01-2 0l-.43-.25a2 2 0 01-1-1.73V4a2 2 0 00-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

const iconMap: Record<TabKey, React.FC<{ active: boolean }>> = {
  chart: ChartIcon,
  dashboard: DashboardIcon,
  trades: TradesIcon,
  analytics: AnalyticsIcon,
  settings: SettingsIcon,
};

export const NAV_HEIGHT = 56;

export function BottomNav() {
  const pathname = usePathname();
  const haptic = useHaptic();

  return (
    <nav
      className="nav-bar"
      role="tablist"
      aria-label="Main navigation"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-around",
          height: `${NAV_HEIGHT}px`,
          maxWidth: "500px",
          margin: "0 auto",
          padding: "0 4px",
        }}
      >
        {tabs.map((tab) => {
          const isActive = pathname.startsWith(tab.href);
          const Icon = iconMap[tab.key];
          return (
            <Link
              key={tab.key}
              href={tab.href}
              role="tab"
              aria-selected={isActive}
              aria-label={tab.label}
              onClick={() => haptic("tick")}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: "3px",
                minWidth: "52px",
                minHeight: "48px",
                padding: "6px 8px",
                textDecoration: "none",
                WebkitTapHighlightColor: "transparent",
                position: "relative",
              }}
            >
              <div style={{ position: "relative" }}>
                <Icon active={isActive} />
                {isActive && (
                  <div
                    style={{
                      position: "absolute",
                      inset: "-6px",
                      borderRadius: "50%",
                      backgroundColor: "#2962ff",
                      opacity: 0.2,
                      filter: "blur(8px)",
                    }}
                    aria-hidden="true"
                  />
                )}
              </div>
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 500,
                  lineHeight: 1,
                  color: isActive ? "#2962ff" : "#787b86",
                  fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
                }}
              >
                {tab.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
