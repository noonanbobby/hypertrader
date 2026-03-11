"use client";

import { useState } from "react";
import { useTrades } from "@/hooks/use-api";
import { TradesTable } from "@/components/trades/trades-table";
import { TradesFilters } from "@/components/trades/trades-filters";
import { TradeDetailDialog } from "@/components/trades/trade-detail-dialog";
import { Button } from "@/components/ui/button";
import type { Trade } from "@/types";
import { Download, ArrowLeftRight } from "lucide-react";

export default function TradesPage() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const { data: trades } = useTrades(filters);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);

  const handleExportCSV = () => {
    if (!trades?.length) return;
    const headers = [
      "ID", "Symbol", "Side", "Leverage", "Entry Price", "Exit Price",
      "Quantity", "Margin", "Notional", "P&L", "Fees", "Status", "Entry Time", "Exit Time",
    ];
    const rows = trades.map((t) => [
      t.id, t.symbol, t.side, `${t.leverage}x`, t.entry_price, t.exit_price ?? "",
      t.quantity, t.margin_used, t.notional_value, t.realized_pnl, t.fees, t.status,
      t.entry_time, t.exit_time ?? "",
    ]);
    const csv = [headers, ...rows].map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trades-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="relative z-10 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/10">
              <ArrowLeftRight className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Trade History</h1>
              <p className="text-xs text-white/30 mt-0.5">
                {trades?.length ?? 0} trades recorded
              </p>
            </div>
          </div>
        </div>
        <Button variant="outline" onClick={handleExportCSV}>
          <Download className="h-4 w-4" /> Export CSV
        </Button>
      </div>

      <TradesFilters filters={filters} onChange={setFilters} />
      <TradesTable trades={trades ?? []} onSelect={setSelectedTrade} />
      <TradeDetailDialog
        trade={selectedTrade}
        onClose={() => setSelectedTrade(null)}
      />
    </div>
  );
}
