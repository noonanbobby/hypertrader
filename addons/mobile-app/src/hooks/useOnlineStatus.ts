"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

function subscribe(callback: () => void): () => void {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

function getSnapshot(): boolean {
  return navigator.onLine;
}

function getServerSnapshot(): boolean {
  return true;
}

export function useOnlineStatus(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export function useLastOnlineTime(): { isOnline: boolean; lastOnline: Date | null } {
  const isOnline = useOnlineStatus();

  const getLastOnline = useCallback(() => {
    if (isOnline) return new Date();
    const stored = typeof window !== "undefined" ? sessionStorage.getItem("ht-last-online") : null;
    return stored ? new Date(stored) : null;
  }, [isOnline]);

  useEffect(() => {
    if (isOnline) {
      sessionStorage.setItem("ht-last-online", new Date().toISOString());
    }
  }, [isOnline]);

  return { isOnline, lastOnline: getLastOnline() };
}
