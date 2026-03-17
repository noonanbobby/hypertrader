"use client";

import { memo } from "react";
import { useHaptic } from "@/hooks/useHaptic";

export type TradeFilter = "all" | "buys" | "sells" | "profitable" | "losing";
export type AssetFilter = "ALL" | "BTC" | "ETH" | "SOL";

interface FilterChipsProps {
  active: TradeFilter;
  onChange: (filter: TradeFilter) => void;
  activeAsset?: AssetFilter;
  onAssetChange?: (asset: AssetFilter) => void;
}

const filters: { key: TradeFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "buys", label: "Buys" },
  { key: "sells", label: "Sells" },
  { key: "profitable", label: "Profitable" },
  { key: "losing", label: "Losing" },
];

const assetColors: Record<string, string> = { BTC: "#f7931a", ETH: "#627eea", SOL: "#9945ff" };
const assetFilters: AssetFilter[] = ["ALL", "BTC", "ETH", "SOL"];

export const FilterChips = memo(function FilterChips({
  active, onChange, activeAsset = "ALL", onAssetChange,
}: FilterChipsProps) {
  const haptic = useHaptic();

  return (
    <div className="flex flex-col gap-2 px-4 pb-1">
      {/* Asset filter row */}
      {onAssetChange && (
        <div className="flex gap-2" role="tablist" aria-label="Asset filters">
          {assetFilters.map((a) => {
            const isActive = activeAsset === a;
            const color = a === "ALL" ? "#2962ff" : assetColors[a] ?? "#888";
            return (
              <button
                key={a}
                role="tab"
                aria-selected={isActive}
                onClick={() => { haptic("tick"); onAssetChange(a); }}
                className="flex-shrink-0 rounded-full border px-3 py-1 text-xs font-medium transition-default active:scale-95"
                style={{
                  borderColor: isActive ? color : "rgba(42,46,57,0.6)",
                  backgroundColor: isActive ? `${color}20` : "transparent",
                  color: isActive ? color : "#787b86",
                }}
              >
                {a}
              </button>
            );
          })}
        </div>
      )}
      {/* Status filter row */}
      <div className="flex gap-2 overflow-x-auto" role="tablist" aria-label="Trade filters">
        {filters.map(({ key, label }) => {
          const isActive = active === key;
          return (
            <button
              key={key}
              role="tab"
              aria-selected={isActive}
              onClick={() => { haptic("tick"); onChange(key); }}
              className="flex-shrink-0 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-default active:scale-95"
              style={{
                borderColor: isActive ? "#2962ff" : "rgba(42,46,57,0.6)",
                backgroundColor: isActive ? "rgba(41,98,255,0.15)" : "transparent",
                color: isActive ? "#2962ff" : "#787b86",
              }}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
});
