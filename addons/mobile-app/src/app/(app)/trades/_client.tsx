"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWRInfinite from "swr/infinite";
import { fetchTrades } from "@/lib/api";
import { PullToRefresh } from "@/components/ui/PullToRefresh";
import { FilterChips, type TradeFilter, type AssetFilter } from "@/components/trades/FilterChips";
import { TradeCard } from "@/components/trades/TradeCard";
import { TradeDetail } from "@/components/trades/TradeDetail";
import { SkeletonCard } from "@/components/ui/Skeleton";
import type { Trade } from "@/types";

const PAGE_SIZE = 20;

export default function TradesPage() {
  const [filter, setFilter] = useState<TradeFilter>("all");
  const [assetFilter, setAssetFilter] = useState<AssetFilter>("ALL");
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Build query params from filter
  const queryParams = useMemo(() => {
    const params: { side?: string; status?: string } = {};
    if (filter === "buys") params.side = "long";
    if (filter === "sells") params.side = "short";
    return params;
  }, [filter]);

  // SWR Infinite for pagination
  const getKey = useCallback(
    (pageIndex: number, previousPageData: Trade[] | null) => {
      if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
      return { ...queryParams, limit: PAGE_SIZE, offset: pageIndex * PAGE_SIZE };
    },
    [queryParams],
  );

  const {
    data: pages,
    size,
    setSize,
    isLoading,
    isValidating,
    mutate,
  } = useSWRInfinite(
    getKey,
    (params) => fetchTrades(params),
    {
      revalidateOnFocus: true,
      revalidateFirstPage: true,
      errorRetryCount: 3,
    },
  );

  // Flatten and filter results
  const allTrades = useMemo(() => {
    if (!pages) return [];
    let flat = pages.flat();
    // Asset filter
    if (assetFilter !== "ALL") {
      flat = flat.filter((t) => {
        const sym = t.symbol.toUpperCase().replace(/USDT|USDC|USD|-PERP/g, "");
        return sym === assetFilter;
      });
    }
    if (filter === "profitable") return flat.filter((t) => t.realized_pnl !== null && t.realized_pnl > 0);
    if (filter === "losing") return flat.filter((t) => t.realized_pnl !== null && t.realized_pnl < 0);
    return flat;
  }, [pages, filter, assetFilter]);

  const hasMore = pages ? pages[pages.length - 1]?.length === PAGE_SIZE : false;
  const isLoadingMore = isValidating && size > 1;

  // Infinite scroll via intersection observer
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isValidating) {
          setSize((s) => s + 1);
        }
      },
      { rootMargin: "200px" },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isValidating, setSize]);

  const handleRefresh = useCallback(async () => {
    await mutate();
  }, [mutate]);

  const handleFilterChange = useCallback((newFilter: TradeFilter) => {
    setFilter(newFilter);
  }, []);

  const handleTradeTap = useCallback((trade: Trade) => {
    setSelectedTrade(trade);
    setDetailOpen(true);
  }, []);

  const handleDetailClose = useCallback(() => {
    setDetailOpen(false);
  }, []);

  return (
    <PullToRefresh onRefresh={handleRefresh} className="min-h-full">
      <div className="flex flex-col gap-4 pb-4 safe-top">
        {/* Header */}
        <div className="px-4 pt-4">
          <h1 className="text-lg font-semibold" style={{ color: "#d1d4dc" }}>
            Trade History
          </h1>
        </div>

        {/* Filter chips */}
        <FilterChips active={filter} onChange={handleFilterChange} activeAsset={assetFilter} onAssetChange={setAssetFilter} />

        {/* Trade list */}
        <div className="flex flex-col gap-3 px-4">
          {isLoading ? (
            Array.from({ length: 5 }, (_, i) => <SkeletonCard key={i} />)
          ) : allTrades.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center gap-2 rounded-xl border py-12"
              style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
            >
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#787b86" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
              <p className="text-xs" style={{ color: "#787b86" }}>
                {filter === "all" ? "No trades yet" : `No ${filter} trades`}
              </p>
            </div>
          ) : (
            <>
              {allTrades.map((trade) => (
                <TradeCard key={trade.id} trade={trade} onTap={handleTradeTap} />
              ))}

              {/* Infinite scroll sentinel */}
              {hasMore && (
                <div ref={sentinelRef} className="flex justify-center py-4">
                  {isLoadingMore && (
                    <div
                      className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
                      style={{ borderColor: "#2962ff", borderTopColor: "transparent" }}
                    />
                  )}
                </div>
              )}

              {!hasMore && allTrades.length > 0 && (
                <p className="py-4 text-center text-[10px]" style={{ color: "#787b86" }}>
                  All trades loaded
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* Trade detail bottom sheet */}
      <TradeDetail
        trade={selectedTrade}
        open={detailOpen}
        onClose={handleDetailClose}
      />
    </PullToRefresh>
  );
}
