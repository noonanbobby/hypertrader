"use client";

import { useCallback } from "react";

type HapticPattern = "light" | "medium" | "heavy" | "tick";

const patterns: Record<HapticPattern, number[]> = {
  light: [10],
  medium: [20],
  heavy: [30, 10, 30],
  tick: [5],
};

export function useHaptic() {
  const vibrate = useCallback((pattern: HapticPattern = "light") => {
    if (typeof navigator !== "undefined" && "vibrate" in navigator) {
      navigator.vibrate(patterns[pattern]);
    }
  }, []);

  return vibrate;
}
