"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Target,
  ArrowLeftRight,
  BarChart3,
  Settings,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Strategies", href: "/strategies", icon: Target },
  { label: "Trades", href: "/trades", icon: ArrowLeftRight },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

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
      <nav className="flex-1 px-3 py-6 space-y-1">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-white/20 px-3 mb-3">
          Menu
        </p>
        {NAV_ITEMS.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          const Icon = item.icon;
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
              <span className="relative z-10">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-white/[0.04] px-6 py-4">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-400 pulse-dot" />
          <p className="text-[11px] text-white/30">System Online</p>
        </div>
      </div>
    </aside>
  );
}
