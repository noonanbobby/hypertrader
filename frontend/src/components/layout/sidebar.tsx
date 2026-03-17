"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FlaskConical,
  ArrowLeftRight,
  BarChart3,
  Settings,
  Zap,
  Coins,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLiveStatus } from "@/hooks/use-api";

const NAV_SECTIONS = [
  {
    label: "Trading",
    items: [
      { label: "Dashboard", href: "/", icon: LayoutDashboard },
      { label: "Paper Trading", href: "/paper", icon: FlaskConical },
    ],
  },
  {
    label: "History",
    items: [
      { label: "Trades", href: "/trades", icon: ArrowLeftRight },
      { label: "Analytics", href: "/analytics", icon: BarChart3 },
    ],
  },
  {
    label: "System",
    items: [
      { label: "Assets", href: "/assets", icon: Coins },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const { data: liveStatus } = useLiveStatus();

  const isLiveConnected = liveStatus?.configured && liveStatus?.connected;

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-[260px] flex-col border-r border-white/[0.06] bg-[#050810]/80 backdrop-blur-2xl">
      {/* Logo */}
      <div className="flex h-20 items-center gap-3 px-6">
        <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 shadow-lg shadow-blue-500/20">
          <Zap className="h-5 w-5 text-white" />
          <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 blur-lg opacity-40" />
        </div>
        <div>
          <h1 className="text-lg font-bold text-white tracking-tight">
            Hyper<span className="text-gradient-blue">Trader</span>
          </h1>
          <p className="text-[10px] font-medium text-white/30 uppercase tracking-widest">
            Perp Futures
          </p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-5">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/20 px-3 mb-2">
              {section.label}
            </p>
            <div className="space-y-1">
              {section.items.map((item) => {
                const isActive =
                  pathname === item.href ||
                  (item.href !== "/" && pathname.startsWith(item.href));
                const Icon = item.icon;

                // Status indicator for Dashboard and Paper Trading
                let statusDot = null;
                if (item.href === "/") {
                  statusDot = isLiveConnected ? (
                    <div className="h-2 w-2 rounded-full bg-emerald-400 pulse-dot" />
                  ) : liveStatus?.configured ? (
                    <div className="h-2 w-2 rounded-full bg-red-400" />
                  ) : null;
                } else if (item.href === "/paper") {
                  statusDot = (
                    <div className="h-2 w-2 rounded-full bg-amber-400" />
                  );
                }

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                      isActive
                        ? "text-white"
                        : "text-white/40 hover:text-white/70"
                    )}
                  >
                    {isActive && (
                      <div className="absolute inset-0 rounded-xl bg-gradient-to-r from-blue-500/10 to-purple-500/10 border border-blue-500/20" />
                    )}
                    {isActive && (
                      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-full bg-gradient-to-b from-blue-400 to-purple-500" />
                    )}
                    <Icon className={cn("h-4 w-4 relative z-10", isActive && "text-blue-400")} />
                    <span className="relative z-10 flex-1">{item.label}</span>
                    {statusDot && (
                      <span className="relative z-10">{statusDot}</span>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-white/[0.04] px-6 py-4">
        <div className="flex items-center gap-2">
          <div className={cn(
            "h-2 w-2 rounded-full",
            isLiveConnected ? "bg-emerald-400 pulse-dot" : "bg-amber-400"
          )} />
          <p className="text-[11px] text-white/30">
            {isLiveConnected ? "Live Connected" : "Paper Mode"}
          </p>
        </div>
      </div>
    </aside>
  );
}
