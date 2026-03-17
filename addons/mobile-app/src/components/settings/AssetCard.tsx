"use client";

import { useCallback, useState } from "react";
import type { AssetConfig } from "@/types";
import { SettingsSection, SettingsRow, Toggle, SliderRow } from "./SettingsSection";

interface AssetCardProps {
  asset: AssetConfig;
  onUpdate: (coin: string, updates: Partial<AssetConfig>) => Promise<void>;
}

export function AssetCard({ asset, onUpdate }: AssetCardProps) {
  const [expanded, setExpanded] = useState(false);

  const handleUpdate = useCallback(
    (updates: Partial<AssetConfig>) => onUpdate(asset.coin, updates),
    [asset.coin, onUpdate],
  );

  const winRate =
    asset.total_trades > 0
      ? ((asset.winning_trades / asset.total_trades) * 100).toFixed(1)
      : "—";

  return (
    <SettingsSection title={`${asset.coin} — ${asset.display_name}`}>
      <SettingsRow label="Enabled">
        <Toggle
          checked={asset.enabled}
          onChange={(v) => handleUpdate({ enabled: v })}
          label={`Enable ${asset.coin}`}
        />
      </SettingsRow>

      <SliderRow
        label="Trade Amount"
        value={asset.fixed_trade_amount_usd}
        min={10}
        max={500}
        step={1}
        unit="$"
        onChange={(v) => handleUpdate({ fixed_trade_amount_usd: v })}
      />

      <SliderRow
        label="Leverage"
        value={asset.leverage}
        min={1}
        max={asset.max_leverage}
        unit="x"
        onChange={(v) => handleUpdate({ leverage: v })}
      />

      <SliderRow
        label="Max Position"
        value={asset.max_position_pct}
        min={5}
        max={100}
        step={5}
        unit="%"
        onChange={(v) => handleUpdate({ max_position_pct: v })}
      />

      {/* Stats */}
      <SettingsRow label="Trades" value={String(asset.total_trades)} />
      <SettingsRow label="Win Rate" value={`${winRate}%`} />
      <SettingsRow
        label="Total P&L"
        value={`$${asset.total_pnl.toFixed(2)}`}
        valueColor={asset.total_pnl >= 0 ? "#26a69a" : "#ef5350"}
      />

      {/* Advanced toggle */}
      <SettingsRow label="Advanced" onTap={() => setExpanded(!expanded)}>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#787b86"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 0.2s",
          }}
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </SettingsRow>

      {expanded && (
        <>
          {/* Supertrend params */}
          <SliderRow
            label="ST ATR Period"
            value={asset.st_atr_period}
            min={5}
            max={30}
            onChange={(v) => handleUpdate({ st_atr_period: v })}
          />
          <SliderRow
            label="ST Multiplier"
            value={asset.st_multiplier}
            min={1}
            max={10}
            step={0.5}
            unit="x"
            onChange={(v) => handleUpdate({ st_multiplier: v })}
          />

          {/* HTF params */}
          <SliderRow
            label="HTF ST Period"
            value={asset.htf_st_atr_period}
            min={5}
            max={30}
            onChange={(v) => handleUpdate({ htf_st_atr_period: v })}
          />
          <SliderRow
            label="HTF ST Mult"
            value={asset.htf_st_multiplier}
            min={1}
            max={10}
            step={0.5}
            unit="x"
            onChange={(v) => handleUpdate({ htf_st_multiplier: v })}
          />

          {/* ADX params */}
          <SliderRow
            label="ADX Period"
            value={asset.adx_period}
            min={7}
            max={30}
            onChange={(v) => handleUpdate({ adx_period: v })}
          />
          <SliderRow
            label="ADX Minimum"
            value={asset.adx_minimum}
            min={5}
            max={40}
            onChange={(v) => handleUpdate({ adx_minimum: v })}
          />
          <SettingsRow label="ADX Rising Required">
            <Toggle
              checked={asset.adx_rising_required}
              onChange={(v) => handleUpdate({ adx_rising_required: v })}
              label="ADX rising required"
            />
          </SettingsRow>

          {/* Squeeze params */}
          <SettingsRow label="Squeeze Block">
            <Toggle
              checked={asset.squeeze_block}
              onChange={(v) => handleUpdate({ squeeze_block: v })}
              label="Squeeze blocking"
            />
          </SettingsRow>
          <SliderRow
            label="SQZ BB Length"
            value={asset.sqz_bb_length}
            min={10}
            max={40}
            onChange={(v) => handleUpdate({ sqz_bb_length: v })}
          />
          <SliderRow
            label="SQZ BB Mult"
            value={asset.sqz_bb_mult}
            min={1}
            max={4}
            step={0.5}
            unit="x"
            onChange={(v) => handleUpdate({ sqz_bb_mult: v })}
          />
          <SliderRow
            label="SQZ KC Length"
            value={asset.sqz_kc_length}
            min={10}
            max={40}
            onChange={(v) => handleUpdate({ sqz_kc_length: v })}
          />
          <SliderRow
            label="SQZ KC Mult"
            value={asset.sqz_kc_mult}
            min={0.5}
            max={3}
            step={0.5}
            unit="x"
            onChange={(v) => handleUpdate({ sqz_kc_mult: v })}
            last
          />
        </>
      )}
    </SettingsSection>
  );
}
