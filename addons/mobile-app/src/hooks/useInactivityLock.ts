"use client";

import { useCallback, useEffect, useRef } from "react";
import { useAuth } from "./useAuth";

export function useInactivityLock() {
  const { isLocked, isSetup, autoLockMinutes, lock, recordActivity } = useAuth();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    if (!isSetup || isLocked || autoLockMinutes <= 0) return;

    recordActivity();
    timerRef.current = setTimeout(() => {
      lock();
    }, autoLockMinutes * 60 * 1000);
  }, [isSetup, isLocked, autoLockMinutes, lock, recordActivity]);

  useEffect(() => {
    if (!isSetup || isLocked) return;

    const events = ["mousedown", "touchstart", "keydown", "scroll"] as const;
    const handler = () => resetTimer();

    events.forEach((e) => window.addEventListener(e, handler, { passive: true }));
    resetTimer();

    return () => {
      events.forEach((e) => window.removeEventListener(e, handler));
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isSetup, isLocked, resetTimer]);

  // Lock on visibility change (app backgrounded)
  useEffect(() => {
    if (!isSetup || isLocked) return;

    const handler = () => {
      if (document.hidden) {
        // Start a shorter timer when backgrounded
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => {
          lock();
        }, Math.min(autoLockMinutes * 60 * 1000, 60_000));
      } else {
        resetTimer();
      }
    };

    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [isSetup, isLocked, autoLockMinutes, lock, resetTimer]);
}
