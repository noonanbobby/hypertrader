"use client";

import { useState, useCallback } from "react";
import { useToast } from "@/components/ui/toast";
import { useAssets } from "@/hooks/use-api";
import { updateAsset } from "@/lib/api";
import type { AssetConfig, AssetConfigUpdate } from "@/types";
import {
  Coins,
  ChevronDown,
  ChevronUp,
  Save,
  TrendingUp,
  TrendingDown,
  Activity,
} from "lucide-react";

function formatPnl(v: number) {
  const s = v >= 0 ? `+$${v.toFixed(2)}` : `-$${Math.abs(v).toFixed(2)}`;
  return s;
}

function AssetCard({
  asset,
  onSaved,
}: {
  asset: AssetConfig;
  onSaved: () => void;
}) {
  const { addToast } = useToast();
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<AssetConfigUpdate>({});

  const isDirty = Object.keys(form).length > 0;

  const current = { ...asset, ...form };

  const set = (field: keyof AssetConfigUpdate, value: unknown) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const save = useCallback(async () => {
    if (!isDirty) return;
    setSaving(true);
    try {
      await updateAsset(asset.coin, form);
      addToast(`${asset.coin} updated`, "success");
      setForm({});
      onSaved();
    } catch (e: unknown) {
      addToast(`Failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
    } finally {
      setSaving(false);
    }
  }, [isDirty, form, asset.coin, addToast, onSaved]);

  const winRate =
    asset.total_trades > 0
      ? ((asset.winning_trades / asset.total_trades) * 100).toFixed(1)
      : "0.0";

  return (
    <div className="rounded-2xl border border-white/[0.06] bg-[#0a0e1a]/80 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-5 border-b border-white/[0.04]">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/20">
            <span className="text-sm font-bold text-white">
              {asset.coin.slice(0, 3)}
            </span>
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">
              {asset.display_name}
            </h3>
            <p className="text-xs text-white/40">{asset.coin}/USDC Perpetual</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => set("enabled", !current.enabled)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              current.enabled ? "bg-emerald-500/80" : "bg-white/10"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                current.enabled ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 divide-x divide-white/[0.04] border-b border-white/[0.04]">
        <div className="px-4 py-3 text-center">
          <p className="text-[10px] uppercase tracking-wider text-white/30 mb-1">
            Trades
          </p>
          <p className="text-sm font-semibold text-white">
            {asset.total_trades}
          </p>
        </div>
        <div className="px-4 py-3 text-center">
          <p className="text-[10px] uppercase tracking-wider text-white/30 mb-1">
            Win Rate
          </p>
          <p className="text-sm font-semibold text-white">{winRate}%</p>
        </div>
        <div className="px-4 py-3 text-center">
          <p className="text-[10px] uppercase tracking-wider text-white/30 mb-1">
            Total P&L
          </p>
          <p
            className={`text-sm font-semibold ${
              asset.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {formatPnl(asset.total_pnl)}
          </p>
        </div>
      </div>

      {/* Core settings */}
      <div className="p-5 space-y-4">
        <SliderField
          label="Trade Amount"
          value={current.fixed_trade_amount_usd}
          min={5}
          max={500}
          step={1}
          suffix="USD"
          onChange={(v) => set("fixed_trade_amount_usd", v)}
        />
        <SliderField
          label="Leverage"
          value={current.leverage}
          min={1}
          max={asset.max_leverage}
          step={1}
          suffix="x"
          onChange={(v) => set("leverage", v)}
        />
        <SliderField
          label="Max Position"
          value={current.max_position_pct}
          min={5}
          max={100}
          step={1}
          suffix="%"
          onChange={(v) => set("max_position_pct", v)}
        />
      </div>

      {/* Advanced toggle */}
      <div className="border-t border-white/[0.04]">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center justify-between px-5 py-3 text-xs font-medium text-white/40 hover:text-white/60 transition-colors"
        >
          <span className="flex items-center gap-1.5">
            <Activity className="h-3 w-3" />
            Advanced Parameters
          </span>
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>

        {expanded && (
          <div className="px-5 pb-5 space-y-5">
            {/* Supertrend */}
            <fieldset>
              <legend className="text-[10px] uppercase tracking-wider text-white/30 mb-3">
                Supertrend (15m)
              </legend>
              <div className="grid grid-cols-2 gap-3">
                <NumberField
                  label="ATR Period"
                  value={current.st_atr_period}
                  onChange={(v) => set("st_atr_period", v)}
                />
                <NumberField
                  label="Multiplier"
                  value={current.st_multiplier}
                  step={0.1}
                  onChange={(v) => set("st_multiplier", v)}
                />
              </div>
            </fieldset>

            {/* HTF */}
            <fieldset>
              <legend className="text-[10px] uppercase tracking-wider text-white/30 mb-3">
                Higher Timeframe
              </legend>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-[10px] text-white/40 mb-1">
                    Timeframe
                  </label>
                  <select
                    value={current.htf_timeframe}
                    onChange={(e) => set("htf_timeframe", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-sm text-white outline-none"
                  >
                    {["15m", "30m", "1h", "4h", "1d"].map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <NumberField
                  label="ATR Period"
                  value={current.htf_st_atr_period}
                  onChange={(v) => set("htf_st_atr_period", v)}
                />
                <NumberField
                  label="Multiplier"
                  value={current.htf_st_multiplier}
                  step={0.1}
                  onChange={(v) => set("htf_st_multiplier", v)}
                />
              </div>
            </fieldset>

            {/* ADX */}
            <fieldset>
              <legend className="text-[10px] uppercase tracking-wider text-white/30 mb-3">
                ADX Filter
              </legend>
              <div className="grid grid-cols-3 gap-3">
                <NumberField
                  label="Period"
                  value={current.adx_period}
                  onChange={(v) => set("adx_period", v)}
                />
                <NumberField
                  label="Minimum"
                  value={current.adx_minimum}
                  step={1}
                  onChange={(v) => set("adx_minimum", v)}
                />
                <ToggleField
                  label="Rising Required"
                  value={current.adx_rising_required}
                  onChange={(v) => set("adx_rising_required", v)}
                />
              </div>
            </fieldset>

            {/* Squeeze */}
            <fieldset>
              <legend className="text-[10px] uppercase tracking-wider text-white/30 mb-3">
                Squeeze Momentum
              </legend>
              <div className="mb-3">
                <ToggleField
                  label="Block entries during squeeze"
                  value={current.squeeze_block}
                  onChange={(v) => set("squeeze_block", v)}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <NumberField
                  label="BB Length"
                  value={current.sqz_bb_length}
                  onChange={(v) => set("sqz_bb_length", v)}
                />
                <NumberField
                  label="BB Mult"
                  value={current.sqz_bb_mult}
                  step={0.1}
                  onChange={(v) => set("sqz_bb_mult", v)}
                />
                <NumberField
                  label="KC Length"
                  value={current.sqz_kc_length}
                  onChange={(v) => set("sqz_kc_length", v)}
                />
                <NumberField
                  label="KC Mult"
                  value={current.sqz_kc_mult}
                  step={0.1}
                  onChange={(v) => set("sqz_kc_mult", v)}
                />
              </div>
            </fieldset>
          </div>
        )}
      </div>

      {/* Save bar */}
      {isDirty && (
        <div className="border-t border-blue-500/20 bg-blue-500/[0.05] px-5 py-3 flex items-center justify-between">
          <p className="text-xs text-blue-400">Unsaved changes</p>
          <div className="flex gap-2">
            <button
              onClick={() => setForm({})}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white/60 hover:text-white transition-colors"
            >
              Discard
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 transition-colors disabled:opacity-50"
            >
              <Save className="h-3 w-3" />
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Reusable field components ── */

function SliderField({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs text-white/50">{label}</label>
        <span className="text-xs font-medium text-white">
          {value}
          {suffix}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-blue-500 h-1.5"
      />
    </div>
  );
}

function NumberField({
  label,
  value,
  step = 1,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="block text-[10px] text-white/40 mb-1">{label}</label>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-sm text-white outline-none focus:border-blue-500/40"
      />
    </div>
  );
}

function ToggleField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-[10px] text-white/40">{label}</label>
      <button
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
          value ? "bg-blue-500/80" : "bg-white/10"
        }`}
      >
        <span
          className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
            value ? "translate-x-5" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

/* ── Page ── */

export default function AssetsPage() {
  const { data: assets, mutate } = useAssets();

  const enabledCount = assets?.filter((a) => a.enabled).length ?? 0;
  const totalPnl = assets?.reduce((s, a) => s + a.total_pnl, 0) ?? 0;
  const totalTrades = assets?.reduce((s, a) => s + a.total_trades, 0) ?? 0;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20">
            <Coins className="h-5 w-5 text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Assets</h1>
            <p className="text-xs text-white/40">
              Manage trading pairs and per-asset parameters
            </p>
          </div>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-xl border border-white/[0.06] bg-[#0a0e1a]/60 p-4">
          <p className="text-[10px] uppercase tracking-wider text-white/30 mb-1">
            Active Assets
          </p>
          <p className="text-2xl font-bold text-white">
            {enabledCount}
            <span className="text-sm text-white/30 ml-1">
              / {assets?.length ?? 0}
            </span>
          </p>
        </div>
        <div className="rounded-xl border border-white/[0.06] bg-[#0a0e1a]/60 p-4">
          <p className="text-[10px] uppercase tracking-wider text-white/30 mb-1">
            Total Trades
          </p>
          <p className="text-2xl font-bold text-white">{totalTrades}</p>
        </div>
        <div className="rounded-xl border border-white/[0.06] bg-[#0a0e1a]/60 p-4">
          <p className="text-[10px] uppercase tracking-wider text-white/30 mb-1">
            Combined P&L
          </p>
          <div className="flex items-center gap-2">
            {totalPnl >= 0 ? (
              <TrendingUp className="h-4 w-4 text-emerald-400" />
            ) : (
              <TrendingDown className="h-4 w-4 text-red-400" />
            )}
            <p
              className={`text-2xl font-bold ${
                totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {formatPnl(totalPnl)}
            </p>
          </div>
        </div>
      </div>

      {/* Asset cards */}
      {!assets ? (
        <div className="text-center py-12 text-white/30">Loading assets...</div>
      ) : assets.length === 0 ? (
        <div className="text-center py-12 text-white/30">
          No assets configured
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {assets.map((asset) => (
            <AssetCard key={asset.id} asset={asset} onSaved={() => mutate()} />
          ))}
        </div>
      )}
    </div>
  );
}
