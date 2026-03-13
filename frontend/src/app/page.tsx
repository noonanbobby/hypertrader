"use client";

import { useLiveStatus, useLivePortfolio, useLivePositions, useLiveFills } from "@/hooks/use-api";
import { MarketTicker } from "@/components/dashboard/market-ticker";
import { ServiceStatus } from "@/components/dashboard/service-status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Wallet,
  Shield,
  TrendingUp,
  TrendingDown,
  Crosshair,
  ArrowLeftRight,
  AlertTriangle,
  Settings,
} from "lucide-react";
import { formatCurrency, formatPrice } from "@/lib/utils";
import Link from "next/link";

function StatCard({
  icon: Icon,
  label,
  value,
  color,
  valueColor,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  color: string;
  valueColor?: string;
}) {
  return (
    <div className="gradient-border rounded-2xl p-5 backdrop-blur-xl bg-white/[0.02]">
      <div className="flex items-center gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-white/30">
            {label}
          </p>
          <p className={`text-xl font-bold mt-0.5 ${valueColor || "text-white"}`}>{value}</p>
        </div>
      </div>
    </div>
  );
}

function ConnectWalletCard() {
  return (
    <Card>
      <div className="flex flex-col items-center justify-center py-20 px-8">
        <div className="relative flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/10 mb-6">
          <Wallet className="h-10 w-10 text-blue-400" />
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-500 blur-xl opacity-20" />
        </div>
        <h2 className="text-xl font-bold text-white mb-2">Connect Your Wallet</h2>
        <p className="text-white/40 text-sm text-center max-w-md mb-6">
          Configure your Hyperliquid API credentials in Settings to view your live portfolio, positions, and recent fills.
        </p>
        <Link
          href="/settings"
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-500 to-purple-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30 transition-all"
        >
          <Settings className="h-4 w-4" />
          Go to Settings
        </Link>
      </div>
    </Card>
  );
}

function ConnectionError() {
  return (
    <Card>
      <div className="flex flex-col items-center justify-center py-16 px-8">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-500/10 border border-amber-500/20 mb-4">
          <AlertTriangle className="h-8 w-8 text-amber-400" />
        </div>
        <h2 className="text-lg font-bold text-white mb-1">Connection Error</h2>
        <p className="text-white/40 text-sm text-center max-w-md">
          Unable to connect to Hyperliquid. Check your API credentials and try again.
        </p>
      </div>
    </Card>
  );
}

function HLPositionsTable({ positions }: { positions: { symbol: string; side: string; size: number; entry_price: number; mark_price: number; unrealized_pnl: number; leverage: number; liquidation_price: number | null; margin_used: number; notional: number }[] }) {
  if (positions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Crosshair className="h-4 w-4 text-white/30" />
            <CardTitle>Open Positions</CardTitle>
          </div>
        </CardHeader>
        <div className="text-center py-12">
          <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-white/[0.03] mb-4">
            <Crosshair className="h-7 w-7 text-white/10" />
          </div>
          <p className="text-white/30 text-sm">No open positions</p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Crosshair className="h-4 w-4 text-white/30" />
          <CardTitle>Open Positions</CardTitle>
        </div>
        <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-[10px] font-bold text-emerald-400">{positions.length} ACTIVE</span>
        </div>
      </CardHeader>
      <div className="overflow-x-auto -mx-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.04]">
              <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Symbol</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Side</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Lev</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Size</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Entry</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Mark</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Unreal. P&L</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Margin</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Liq Price</th>
              <th className="text-right px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Notional</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos, i) => {
              const positive = pos.unrealized_pnl >= 0;
              return (
                <tr key={`${pos.symbol}-${i}`} className="border-b border-white/[0.03] table-row-hover">
                  <td className="px-6 py-4">
                    <span className="font-semibold text-white">{pos.symbol}</span>
                    <span className="text-white/20 text-xs ml-1">PERP</span>
                  </td>
                  <td className="px-3 py-4">
                    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                      pos.side === "long"
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        : "bg-red-500/10 text-red-400 border border-red-500/20"
                    }`}>
                      {pos.side}
                    </span>
                  </td>
                  <td className="px-3 py-4">
                    <span className="inline-flex items-center rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-bold">
                      {pos.leverage}x
                    </span>
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/80">{pos.size}</td>
                  <td className="px-3 py-4 text-right font-mono text-white/50">{formatPrice(pos.entry_price)}</td>
                  <td className="px-3 py-4 text-right font-mono text-white">{formatPrice(pos.mark_price)}</td>
                  <td className="px-3 py-4 text-right">
                    <span className={`font-bold ${positive ? "text-emerald-400" : "text-red-400"}`}>
                      {formatCurrency(pos.unrealized_pnl)}
                    </span>
                  </td>
                  <td className="px-3 py-4 text-right font-mono text-white/50">{formatCurrency(pos.margin_used)}</td>
                  <td className="px-3 py-4 text-right font-mono text-white/30">
                    {pos.liquidation_price ? formatPrice(pos.liquidation_price) : "—"}
                  </td>
                  <td className="px-6 py-4 text-right font-mono text-white/30">{formatCurrency(pos.notional)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function HLFillsTable({ fills }: { fills: { symbol: string; side: string; size: number; price: number; fee: number; time: number; closed_pnl: number }[] }) {
  if (fills.length === 0) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ArrowLeftRight className="h-4 w-4 text-white/30" />
            <CardTitle>Recent Fills</CardTitle>
          </div>
        </CardHeader>
        <div className="text-center py-12">
          <p className="text-white/30 text-sm">No recent fills</p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <ArrowLeftRight className="h-4 w-4 text-white/30" />
          <CardTitle>Recent Fills</CardTitle>
        </div>
      </CardHeader>
      <div className="overflow-x-auto -mx-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.04]">
              <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Time</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Symbol</th>
              <th className="text-left px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Side</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Size</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Price</th>
              <th className="text-right px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Fee</th>
              <th className="text-right px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-white/30">Closed PNL</th>
            </tr>
          </thead>
          <tbody>
            {fills.map((fill, i) => {
              const pnlPositive = fill.closed_pnl >= 0;
              const dt = new Date(fill.time);
              const timeStr = dt.toLocaleString(undefined, {
                month: "short", day: "numeric",
                hour: "2-digit", minute: "2-digit", second: "2-digit",
              });
              return (
                <tr key={`${fill.symbol}-${fill.time}-${i}`} className="border-b border-white/[0.03] table-row-hover">
                  <td className="px-6 py-3 text-white/40 text-xs font-mono">{timeStr}</td>
                  <td className="px-3 py-3">
                    <span className="font-semibold text-white">{fill.symbol}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                      fill.side === "buy" || fill.side === "long"
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        : "bg-red-500/10 text-red-400 border border-red-500/20"
                    }`}>
                      {fill.side}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-white/80">{fill.size}</td>
                  <td className="px-3 py-3 text-right font-mono text-white/50">{formatPrice(fill.price)}</td>
                  <td className="px-3 py-3 text-right font-mono text-white/30">{formatCurrency(fill.fee)}</td>
                  <td className="px-6 py-3 text-right">
                    {fill.closed_pnl !== 0 ? (
                      <span className={`font-bold ${pnlPositive ? "text-emerald-400" : "text-red-400"}`}>
                        {formatCurrency(fill.closed_pnl)}
                      </span>
                    ) : (
                      <span className="text-white/20">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function DashboardPage() {
  const { data: status, isLoading: statusLoading } = useLiveStatus();
  const { data: portfolio } = useLivePortfolio();
  const { data: positions } = useLivePositions();
  const { data: fills } = useLiveFills();

  const isConfigured = status?.configured ?? false;
  const isConnected = status?.connected ?? false;

  return (
    <div className="relative z-10 space-y-6">
      {/* Service Status */}
      <ServiceStatus />

      {/* Market Ticker */}
      <MarketTicker />

      {/* If not configured, show connect card */}
      {!statusLoading && !isConfigured && <ConnectWalletCard />}

      {/* If configured but not connected, show error */}
      {!statusLoading && isConfigured && !isConnected && <ConnectionError />}

      {/* Live Portfolio */}
      {isConfigured && isConnected && (
        <>
          {/* Portfolio Stats */}
          <div className="grid grid-cols-4 gap-4">
            <StatCard
              icon={Wallet}
              label="Account Value"
              value={formatCurrency(portfolio?.account_value ?? 0)}
              color="bg-blue-500/10 text-blue-400"
            />
            <StatCard
              icon={Shield}
              label="Available Balance"
              value={formatCurrency(portfolio?.available_balance ?? 0)}
              color="bg-emerald-500/10 text-emerald-400"
            />
            <StatCard
              icon={TrendingUp}
              label="Margin Used"
              value={formatCurrency(portfolio?.total_margin_used ?? 0)}
              color="bg-amber-500/10 text-amber-400"
            />
            <StatCard
              icon={portfolio?.total_unrealized_pnl ?? 0 >= 0 ? TrendingUp : TrendingDown}
              label="Unrealized PNL"
              value={formatCurrency(portfolio?.total_unrealized_pnl ?? 0)}
              color={(portfolio?.total_unrealized_pnl ?? 0) >= 0 ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"}
              valueColor={(portfolio?.total_unrealized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}
            />
          </div>

          {/* Positions */}
          <HLPositionsTable positions={positions ?? []} />

          {/* Recent Fills */}
          <HLFillsTable fills={fills ?? []} />
        </>
      )}
    </div>
  );
}
