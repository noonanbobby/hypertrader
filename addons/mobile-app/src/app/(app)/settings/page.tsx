"use client";

import { useCallback, useState } from "react";
import { useSettings, useSystemStatus } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { updateSettings } from "@/lib/api";
import { PullToRefresh } from "@/components/ui/PullToRefresh";
import { StatusDot } from "@/components/ui/Badge";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { PinPad } from "@/components/auth/PinPad";
import {
  SettingsSection,
  SettingsRow,
  Toggle,
  SliderRow,
} from "@/components/settings/SettingsSection";
import { SoundSettings } from "@/components/settings/SoundSettings";
import { Skeleton } from "@/components/ui/Skeleton";
import { useHaptic } from "@/hooks/useHaptic";
import type { AppSettings } from "@/types";

export default function SettingsPage() {
  const { data: settings, isLoading: settingsLoading, mutate: refreshSettings } = useSettings();
  const { data: status, isLoading: statusLoading, mutate: refreshStatus } = useSystemStatus();
  const { biometricsEnabled, autoLockMinutes, setBiometrics, setAutoLockMinutes } = useAuth();
  const haptic = useHaptic();

  const [changePinOpen, setChangePinOpen] = useState(false);
  const [pinStep, setPinStep] = useState<"current" | "new" | "confirm">("current");
  const [currentPin, setCurrentPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const { changePin } = useAuth();

  const handleRefresh = useCallback(async () => {
    await Promise.all([refreshSettings(), refreshStatus()]);
  }, [refreshSettings, refreshStatus]);

  const handleSettingChange = useCallback(
    async (updates: Partial<AppSettings>) => {
      haptic("tick");
      await updateSettings(updates);
      await refreshSettings();
    },
    [haptic, refreshSettings],
  );

  const handleChangePinStart = useCallback(() => {
    setChangePinOpen(true);
    setPinStep("current");
    setCurrentPin("");
    setNewPin("");
    setPinError(null);
  }, []);

  const handlePinInput = useCallback(
    async (pin: string) => {
      setPinError(null);
      if (pinStep === "current") {
        setCurrentPin(pin);
        setPinStep("new");
      } else if (pinStep === "new") {
        setNewPin(pin);
        setPinStep("confirm");
      } else {
        if (pin !== newPin) {
          setPinError("PINs don't match");
          setPinStep("new");
          setNewPin("");
          return;
        }
        const success = await changePin(currentPin, pin);
        if (success) {
          haptic("medium");
          setChangePinOpen(false);
        } else {
          setPinError("Current PIN incorrect");
          setPinStep("current");
          setCurrentPin("");
          setNewPin("");
        }
      }
    },
    [pinStep, currentPin, newPin, changePin, haptic],
  );

  const copyToClipboard = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text);
        haptic("light");
      } catch {
        // Clipboard not available
      }
    },
    [haptic],
  );

  return (
    <PullToRefresh onRefresh={handleRefresh} className="min-h-full">
      <div className="flex flex-col gap-6 p-4 pb-8 safe-top">
        <h1 className="text-lg font-semibold" style={{ color: "#d1d4dc" }}>
          Settings
        </h1>

        {/* System Status */}
        <SettingsSection title="System Status">
          {statusLoading ? (
            <>
              <SettingsRow label="Backend"><Skeleton width={60} height={14} /></SettingsRow>
              <SettingsRow label="Ngrok"><Skeleton width={60} height={14} /></SettingsRow>
              <SettingsRow label="WebSocket"><Skeleton width={60} height={14} /></SettingsRow>
              <SettingsRow label="Telegram" last><Skeleton width={60} height={14} /></SettingsRow>
            </>
          ) : status ? (
            <>
              <SettingsRow label="Backend">
                <StatusDot status={status.backend.status} label={status.backend.message} />
              </SettingsRow>
              <SettingsRow label="Ngrok">
                <StatusDot status={status.ngrok.status} label={status.ngrok.message} />
              </SettingsRow>
              {status.ngrok.url && (
                <SettingsRow
                  label="Webhook URL"
                  onTap={() => copyToClipboard(status.ngrok.url!)}
                >
                  <span className="flex items-center gap-1 text-xs" style={{ color: "#2962ff" }}>
                    <span className="max-w-[140px] truncate font-mono">{status.ngrok.url}</span>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                    </svg>
                  </span>
                </SettingsRow>
              )}
              <SettingsRow label="WebSocket">
                <StatusDot status={status.websocket.status} label={status.websocket.message} />
              </SettingsRow>
              <SettingsRow label="Telegram" last>
                <StatusDot status={status.telegram.status} label={status.telegram.message} />
              </SettingsRow>
            </>
          ) : (
            <SettingsRow label="Status" value="Unable to connect" valueColor="#ef5350" last />
          )}
        </SettingsSection>

        {/* Asset Management Link */}
        <SettingsSection title="Multi-Asset Trading">
          <SettingsRow label="Manage Assets" onTap={() => window.location.href = "/assets"} last>
            <span className="flex items-center gap-1 text-xs" style={{ color: "#2962ff" }}>
              Configure
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </span>
          </SettingsRow>
        </SettingsSection>

        {/* Trading Config */}
        <SettingsSection title="Trading Configuration">
          {settingsLoading || !settings ? (
            <>
              <SettingsRow label="Leverage"><Skeleton width={40} height={14} /></SettingsRow>
              <SettingsRow label="Position Size"><Skeleton width={40} height={14} /></SettingsRow>
              <SettingsRow label="Max Position %" last><Skeleton width={40} height={14} /></SettingsRow>
            </>
          ) : (
            <>
              <SliderRow
                label="Leverage"
                value={settings.leverage}
                min={1}
                max={50}
                unit="x"
                onChange={(v) => handleSettingChange({ leverage: v })}
              />
              <SliderRow
                label="Position Size"
                value={settings.default_size_pct}
                min={1}
                max={100}
                unit="%"
                onChange={(v) => handleSettingChange({ default_size_pct: v })}
              />
              <SliderRow
                label="Max Position"
                value={settings.default_max_position_pct}
                min={10}
                max={100}
                step={5}
                unit="%"
                onChange={(v) => handleSettingChange({ default_max_position_pct: v })}
              />
              <SliderRow
                label="Max Drawdown"
                value={settings.default_max_drawdown_pct}
                min={5}
                max={50}
                step={5}
                unit="%"
                onChange={(v) => handleSettingChange({ default_max_drawdown_pct: v })}
              />
              <SliderRow
                label="Daily Loss Limit"
                value={settings.default_daily_loss_limit}
                min={0}
                max={5000}
                step={100}
                unit=""
                onChange={(v) => handleSettingChange({ default_daily_loss_limit: v })}
                last
              />
            </>
          )}
        </SettingsSection>

        {/* Limit Orders */}
        <SettingsSection title="Limit Orders">
          {settingsLoading || !settings ? (
            <SettingsRow label="Use Limit Orders" last><Skeleton width={50} height={30} /></SettingsRow>
          ) : (
            <>
              <SettingsRow label="Use Limit Orders">
                <Toggle
                  checked={settings.use_limit_orders}
                  onChange={(v) => handleSettingChange({ use_limit_orders: v })}
                  label="Use limit orders"
                />
              </SettingsRow>
              {settings.use_limit_orders && (
                <>
                  <SliderRow
                    label="Timeout"
                    value={settings.limit_order_timeout_sec}
                    min={5}
                    max={120}
                    step={5}
                    unit="s"
                    onChange={(v) => handleSettingChange({ limit_order_timeout_sec: v })}
                  />
                  <SliderRow
                    label="Offset"
                    value={settings.limit_order_offset_pct}
                    min={0}
                    max={1}
                    step={0.01}
                    unit="%"
                    onChange={(v) => handleSettingChange({ limit_order_offset_pct: v })}
                    last
                  />
                </>
              )}
              {!settings.use_limit_orders && <div />}
            </>
          )}
        </SettingsSection>

        {/* Notifications */}
        <SettingsSection title="Notifications">
          {settingsLoading || !settings ? (
            <>
              <SettingsRow label="Trade Alerts"><Skeleton width={50} height={30} /></SettingsRow>
              <SettingsRow label="Close Alerts"><Skeleton width={50} height={30} /></SettingsRow>
              <SettingsRow label="Risk Alerts" last><Skeleton width={50} height={30} /></SettingsRow>
            </>
          ) : (
            <>
              <SettingsRow label="Trade Open Alerts">
                <Toggle
                  checked={settings.notify_trade_open}
                  onChange={(v) => handleSettingChange({ notify_trade_open: v })}
                  label="Trade open notifications"
                />
              </SettingsRow>
              <SettingsRow label="Trade Close Alerts">
                <Toggle
                  checked={settings.notify_trade_close}
                  onChange={(v) => handleSettingChange({ notify_trade_close: v })}
                  label="Trade close notifications"
                />
              </SettingsRow>
              <SettingsRow label="Risk Breach Alerts" last>
                <Toggle
                  checked={settings.notify_risk_breach}
                  onChange={(v) => handleSettingChange({ notify_risk_breach: v })}
                  label="Risk breach notifications"
                />
              </SettingsRow>
            </>
          )}
        </SettingsSection>

        {/* Sounds & Haptics */}
        <SoundSettings />

        {/* Security */}
        <SettingsSection title="Security">
          <SettingsRow label="Change PIN" onTap={handleChangePinStart}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#787b86" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </SettingsRow>
          <SettingsRow label="Biometric Lock">
            <Toggle
              checked={biometricsEnabled}
              onChange={setBiometrics}
              label="Biometric lock"
            />
          </SettingsRow>
          <SettingsRow label="Auto-Lock" last>
            <select
              value={autoLockMinutes}
              onChange={(e) => setAutoLockMinutes(Number(e.target.value))}
              className="rounded-lg border bg-transparent px-2 py-1 text-xs font-mono"
              style={{ borderColor: "rgba(42,46,57,0.6)", color: "#d1d4dc" }}
              aria-label="Auto-lock timeout"
            >
              <option value={1}>1 min</option>
              <option value={5}>5 min</option>
              <option value={15}>15 min</option>
              <option value={0}>Never</option>
            </select>
          </SettingsRow>
        </SettingsSection>

        {/* About */}
        <SettingsSection title="About">
          <SettingsRow label="Version" value="1.0.0" />
          <SettingsRow
            label="Trading Mode"
            value={settings?.trading_mode ?? "—"}
            valueColor={settings?.trading_mode === "live" ? "#26a69a" : "#ff9800"}
          />
          <SettingsRow
            label="Trading Paused"
            value={settings?.trading_paused ? "Yes" : "No"}
            valueColor={settings?.trading_paused ? "#ef5350" : "#26a69a"}
            last
          />
        </SettingsSection>
      </div>

      {/* Change PIN bottom sheet */}
      <BottomSheet
        open={changePinOpen}
        onClose={() => setChangePinOpen(false)}
        title="Change PIN"
        snapPoints={[0.65]}
      >
        <div className="py-4">
          <PinPad
            onComplete={handlePinInput}
            error={pinError}
            title={
              pinStep === "current"
                ? "Enter Current PIN"
                : pinStep === "new"
                  ? "Enter New PIN"
                  : "Confirm New PIN"
            }
            subtitle={
              pinStep === "current"
                ? "Verify your identity"
                : pinStep === "new"
                  ? "Choose a new 4-digit PIN"
                  : "Enter the new PIN again"
            }
          />
        </div>
      </BottomSheet>
    </PullToRefresh>
  );
}
