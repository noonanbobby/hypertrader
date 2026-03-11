"use client";

import { useWebSocket } from "@/hooks/use-websocket";
import { useDashboard } from "@/hooks/use-api";
import { ModeBadge } from "./mode-badge";
import { Wifi, WifiOff } from "lucide-react";

export function Header() {
  const { connected } = useWebSocket();
  const { data } = useDashboard();

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-white/[0.04] bg-[#050810]/60 backdrop-blur-2xl px-8">
      <div className="flex items-center gap-4">
        <ModeBadge mode={data?.trading_mode || "paper"} />
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-xs">
          {connected ? (
            <>
              <div className="relative">
                <Wifi className="h-3.5 w-3.5 text-emerald-400" />
                <div className="absolute inset-0 animate-ping">
                  <Wifi className="h-3.5 w-3.5 text-emerald-400 opacity-30" />
                </div>
              </div>
              <span className="text-emerald-400 font-medium">Live</span>
            </>
          ) : (
            <>
              <WifiOff className="h-3.5 w-3.5 text-red-400" />
              <span className="text-red-400 font-medium">Offline</span>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
