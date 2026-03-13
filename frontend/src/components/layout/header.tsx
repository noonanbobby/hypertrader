"use client";

import { useWebSocket } from "@/hooks/use-websocket";
import { useDashboard } from "@/hooks/use-api";
import { useSettings } from "@/hooks/use-api";
import { updateSettings } from "@/lib/api";
import { ModeBadge } from "./mode-badge";
import { Wifi, WifiOff, Pause, Play } from "lucide-react";
import { useState } from "react";
import { mutate } from "swr";

export function Header() {
  const { connected } = useWebSocket();
  const { data } = useDashboard();
  const { data: settings } = useSettings();
  const [toggling, setToggling] = useState(false);

  const paused = settings?.trading_paused ?? false;

  const handleTogglePause = async () => {
    if (toggling) return;
    setToggling(true);
    try {
      await updateSettings({ trading_paused: !paused });
      mutate("/api/settings");
    } catch (e) {
      console.error("Failed to toggle pause:", e);
    } finally {
      setToggling(false);
    }
  };

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-white/[0.04] bg-[#050810]/60 backdrop-blur-2xl px-8">
      <div className="flex items-center gap-4">
        <ModeBadge mode={data?.trading_mode || "paper"} />
        <button
          onClick={handleTogglePause}
          disabled={toggling}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ${
            paused
              ? "bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse"
              : "bg-emerald-500/10 text-emerald-400/70 border border-emerald-500/20 hover:bg-emerald-500/20"
          } ${toggling ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
        >
          {paused ? (
            <>
              <Pause className="h-3.5 w-3.5" />
              PAUSED
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5" />
              TRADING
            </>
          )}
        </button>
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
