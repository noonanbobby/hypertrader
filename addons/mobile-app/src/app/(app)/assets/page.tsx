"use client";

import { useCallback } from "react";
import { useAssetConfigs } from "@/hooks/useApi";
import { updateAssetConfig } from "@/lib/api";
import { PullToRefresh } from "@/components/ui/PullToRefresh";
import { AssetCard } from "@/components/settings/AssetCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { useHaptic } from "@/hooks/useHaptic";
import type { AssetConfig } from "@/types";

export default function AssetsPage() {
  const { data: assets, isLoading, mutate } = useAssetConfigs();
  const haptic = useHaptic();

  const handleUpdate = useCallback(
    async (coin: string, updates: Partial<AssetConfig>) => {
      haptic("tick");
      await updateAssetConfig(coin, updates);
      await mutate();
    },
    [haptic, mutate],
  );

  return (
    <PullToRefresh onRefresh={async () => { await mutate(); }} className="min-h-full">
      <div className="flex flex-col gap-6 p-4 pb-8 safe-top">
        <div className="flex items-center gap-3">
          <button
            onClick={() => window.history.back()}
            className="flex h-8 w-8 items-center justify-center rounded-lg"
            style={{ backgroundColor: "rgba(42,46,57,0.4)" }}
            aria-label="Back"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#d1d4dc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <h1 className="text-lg font-semibold" style={{ color: "#d1d4dc" }}>
            Asset Configuration
          </h1>
        </div>

        {isLoading ? (
          <div className="flex flex-col gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="rounded-xl border p-4" style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}>
                <Skeleton width="100%" height={120} />
              </div>
            ))}
          </div>
        ) : assets && assets.length > 0 ? (
          assets.map((asset) => (
            <AssetCard key={asset.coin} asset={asset} onUpdate={handleUpdate} />
          ))
        ) : (
          <div className="rounded-xl border p-6 text-center" style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}>
            <p className="text-sm" style={{ color: "#787b86" }}>
              No assets configured. Start the backend to seed defaults.
            </p>
          </div>
        )}
      </div>
    </PullToRefresh>
  );
}
