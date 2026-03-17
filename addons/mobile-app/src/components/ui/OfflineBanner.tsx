"use client";

import { useLastOnlineTime } from "@/hooks/useOnlineStatus";
import { useEffect, useState } from "react";

function formatTimeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function OfflineBanner() {
  const { isOnline, lastOnline } = useLastOnlineTime();
  const [, forceUpdate] = useState(0);

  // Update the "time ago" display every 30 seconds
  useEffect(() => {
    if (isOnline) return;
    const interval = setInterval(() => forceUpdate((n) => n + 1), 30_000);
    return () => clearInterval(interval);
  }, [isOnline]);

  if (isOnline) return null;

  return (
    <div
      className="flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium"
      style={{ backgroundColor: "rgba(255,152,0,0.15)", color: "#ff9800" }}
      role="status"
      aria-live="polite"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <line x1="1" y1="1" x2="23" y2="23" />
        <path d="M16.72 11.06A10.94 10.94 0 0119 12.55" />
        <path d="M5 12.55a10.94 10.94 0 015.17-2.39" />
        <path d="M10.71 5.05A16 16 0 0122.56 9" />
        <path d="M1.42 9a15.91 15.91 0 014.7-2.88" />
        <path d="M8.53 16.11a6 6 0 016.95 0" />
        <line x1="12" y1="20" x2="12.01" y2="20" />
      </svg>
      <span>
        Offline{lastOnline ? ` · Last updated ${formatTimeAgo(lastOnline)}` : ""}
      </span>
    </div>
  );
}
