"use client";

import { memo, useCallback, useState } from "react";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { SlideToConfirm } from "@/components/ui/SlideToConfirm";
import { useHaptic } from "@/hooks/useHaptic";

interface KillSwitchProps {
  onConfirm: () => Promise<void>;
  hasPositions: boolean;
}

export const KillSwitch = memo(function KillSwitch({
  onConfirm,
  hasPositions,
}: KillSwitchProps) {
  const haptic = useHaptic();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<"success" | "error" | null>(null);

  const handleFabPress = useCallback(() => {
    if (!hasPositions) return;
    haptic("medium");
    setSheetOpen(true);
    setResult(null);
  }, [hasPositions, haptic]);

  const handleConfirm = useCallback(async () => {
    setExecuting(true);
    try {
      await onConfirm();
      setResult("success");
      haptic("heavy");
      setTimeout(() => {
        setSheetOpen(false);
        setResult(null);
      }, 1500);
    } catch {
      setResult("error");
      haptic("heavy");
    } finally {
      setExecuting(false);
    }
  }, [onConfirm, haptic]);

  return (
    <>
      {/* FAB */}
      <button
        onClick={handleFabPress}
        disabled={!hasPositions}
        className="fixed bottom-[84px] right-4 z-30 flex h-14 w-14 items-center justify-center rounded-full transition-default active:scale-90 disabled:opacity-30"
        style={{
          backgroundColor: "#ef5350",
          boxShadow: hasPositions
            ? "0 4px 20px rgba(239,83,80,0.4)"
            : "0 4px 20px rgba(0,0,0,0.3)",
        }}
        aria-label="Emergency close all positions"
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 6L6 18" />
          <path d="M6 6l12 12" />
        </svg>
        {hasPositions && (
          <span
            className="absolute inset-0 rounded-full animate-pulse-subtle"
            style={{ border: "2px solid rgba(239,83,80,0.4)" }}
            aria-hidden="true"
          />
        )}
      </button>

      {/* Confirmation sheet */}
      <BottomSheet
        open={sheetOpen}
        onClose={() => { setSheetOpen(false); setResult(null); }}
        title="Close All Positions"
        snapPoints={[0.35]}
      >
        <div className="flex flex-col gap-5 py-2">
          {result === null && (
            <>
              <div className="flex items-center gap-3 rounded-xl p-3" style={{ backgroundColor: "rgba(239,83,80,0.1)" }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef5350" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
                <p className="text-xs" style={{ color: "#d1d4dc" }}>
                  This will market-close every open position immediately. This action cannot be undone.
                </p>
              </div>

              <SlideToConfirm
                onConfirm={handleConfirm}
                label="Slide to close all"
                confirmLabel="Closing..."
                variant="danger"
                disabled={executing}
              />
            </>
          )}

          {result === "success" && (
            <div className="flex flex-col items-center gap-3 py-4 animate-fade-in">
              <div className="flex h-14 w-14 items-center justify-center rounded-full" style={{ backgroundColor: "rgba(38,166,154,0.15)" }}>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#26a69a" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
              <p className="text-sm font-medium" style={{ color: "#26a69a" }}>
                All positions closed
              </p>
            </div>
          )}

          {result === "error" && (
            <div className="flex flex-col items-center gap-3 py-4 animate-fade-in">
              <div className="flex h-14 w-14 items-center justify-center rounded-full" style={{ backgroundColor: "rgba(239,83,80,0.15)" }}>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ef5350" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="15" y1="9" x2="9" y2="15" />
                  <line x1="9" y1="9" x2="15" y2="15" />
                </svg>
              </div>
              <p className="text-sm font-medium" style={{ color: "#ef5350" }}>
                Failed to close positions
              </p>
              <button
                onClick={handleConfirm}
                className="rounded-lg px-6 py-2 text-xs font-medium transition-default active:scale-95"
                style={{ backgroundColor: "#ef5350", color: "#fff" }}
              >
                Retry
              </button>
            </div>
          )}
        </div>
      </BottomSheet>
    </>
  );
});
