"use client";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, X, Filter } from "lucide-react";

interface TradesFiltersProps {
  filters: Record<string, string>;
  onChange: (filters: Record<string, string>) => void;
}

export function TradesFilters({ filters, onChange }: TradesFiltersProps) {
  const update = (key: string, value: string) => {
    const next = { ...filters };
    if (value) next[key] = value;
    else delete next[key];
    onChange(next);
  };

  const clear = () => onChange({});

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <div className="flex items-center gap-2 text-white/20">
        <Filter className="h-3.5 w-3.5" />
        <span className="text-[10px] font-semibold uppercase tracking-wider">Filters</span>
      </div>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-white/20" />
        <Input
          placeholder="Symbol..."
          value={filters.symbol ?? ""}
          onChange={(e) => update("symbol", e.target.value)}
          className="pl-9 w-32 h-9 text-xs"
        />
      </div>
      <select
        value={filters.side ?? ""}
        onChange={(e) => update("side", e.target.value)}
        className="h-9 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 text-xs text-white/60 focus:outline-none focus:ring-2 focus:ring-blue-500/30 transition-all cursor-pointer"
      >
        <option value="">All Sides</option>
        <option value="long">Long</option>
        <option value="short">Short</option>
      </select>
      <select
        value={filters.status ?? ""}
        onChange={(e) => update("status", e.target.value)}
        className="h-9 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 text-xs text-white/60 focus:outline-none focus:ring-2 focus:ring-blue-500/30 transition-all cursor-pointer"
      >
        <option value="">All Status</option>
        <option value="open">Open</option>
        <option value="closed">Closed</option>
      </select>
      {Object.keys(filters).length > 0 && (
        <Button variant="ghost" size="sm" onClick={clear}>
          <X className="h-3 w-3" /> Clear
        </Button>
      )}
    </div>
  );
}
