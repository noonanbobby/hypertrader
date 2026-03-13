"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useDashboard, useSettings } from "@/hooks/use-api";
import { getHealth, updateSettings, testTelegram } from "@/lib/api";
import { API_BASE_URL } from "@/lib/constants";
import type { AppSettingsUpdate } from "@/types";
import {
  Copy,
  RefreshCw,
  Settings,
  Wifi,
  WifiOff,
  Shield,
  Webhook,
  Zap,
  FileCode2,
  Key,
  DollarSign,
  AlertTriangle,
  Save,
  X,
  Eye,
  EyeOff,
  Send,
  Bell,
} from "lucide-react";

type FormState = AppSettingsUpdate;

export default function SettingsPage() {
  const { addToast } = useToast();
  const { data: dashboard, mutate: mutateDashboard } = useDashboard();
  const { data: appSettings, mutate: mutateSettings } = useSettings();
  const [health, setHealth] = useState<{
    status: string;
    mode: string;
    version: string;
  } | null>(null);
  const [form, setForm] = useState<FormState>({});
  const [saving, setSaving] = useState(false);
  const [sendingTest, setSendingTest] = useState(false);
  const [liveConfirmOpen, setLiveConfirmOpen] = useState(false);
  const [editingSecrets, setEditingSecrets] = useState<Record<string, boolean>>({});

  const [webhookUrl, setWebhookUrl] = useState(`${API_BASE_URL}/api/webhook`);
  const isDirty = Object.keys(form).length > 0;
  const frontendVersion = process.env.NEXT_PUBLIC_APP_VERSION ?? "—";

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const setField = useCallback(
    <K extends keyof FormState>(key: K, value: FormState[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const discardChanges = () => {
    setForm({});
    setEditingSecrets({});
  };

  const saveChanges = async () => {
    if (!isDirty) return;
    setSaving(true);
    try {
      await updateSettings(form);
      await mutateSettings();
      await mutateDashboard();
      setForm({});
      setEditingSecrets({});
      addToast("Settings saved successfully", "success");
    } catch (e) {
      addToast(
        `Failed to save: ${e instanceof Error ? e.message : "Unknown error"}`,
        "error"
      );
    } finally {
      setSaving(false);
    }
  };

  const handleModeChange = (mode: "paper" | "live") => {
    if (mode === "live" && appSettings?.trading_mode !== "live" && form.trading_mode !== "live") {
      setLiveConfirmOpen(true);
      return;
    }
    setField("trading_mode", mode);
  };

  const confirmLiveMode = () => {
    setField("trading_mode", "live");
    setLiveConfirmOpen(false);
  };

  const handleTestTelegram = async () => {
    setSendingTest(true);
    try {
      const res = await testTelegram();
      if (res.success) {
        addToast("Test message sent to Telegram!", "success");
      } else {
        addToast(`Telegram test failed: ${res.message}`, "error");
      }
    } catch {
      addToast("Failed to send test message", "error");
    } finally {
      setSendingTest(false);
    }
  };

  const copyWebhookUrl = () => {
    navigator.clipboard.writeText(webhookUrl);
    addToast("Webhook URL copied to clipboard", "success");
  };

  const testWebhook = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/webhook`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          secret: "your-webhook-secret",
          strategy: "Test Strategy",
          action: "buy",
          symbol: "BTC",
          quantity: 0.001,
          message: "Test webhook from settings",
        }),
      });
      const data = await res.json();
      if (data.success) {
        addToast("Test webhook sent successfully!", "success");
      } else {
        addToast(`Webhook failed: ${data.message}`, "error");
      }
    } catch {
      addToast("Failed to connect to backend", "error");
    }
  };

  // Resolve displayed value: form override > server value > fallback
  const val = <K extends keyof FormState>(key: K): NonNullable<FormState[K]> => {
    if (form[key] !== undefined) return form[key] as NonNullable<FormState[K]>;
    if (appSettings && key in appSettings)
      return appSettings[key as keyof typeof appSettings] as NonNullable<FormState[K]>;
    return "" as NonNullable<FormState[K]>;
  };

  const currentMode = (form.trading_mode ?? appSettings?.trading_mode ?? "paper") as string;

  // Secret field helper
  const renderSecretField = (
    key: "webhook_secret" | "hl_api_key" | "hl_api_secret",
    label: string
  ) => {
    const savedValue = appSettings?.[key] ?? "";
    const hasValue = savedValue.length > 0 && savedValue !== "****";
    const isEditing = editingSecrets[key] || !hasValue;

    return (
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
          {label}
        </label>
        <div className="flex gap-2">
          {isEditing ? (
            <Input
              type="text"
              placeholder="Enter new value..."
              value={form[key] ?? ""}
              onChange={(e) => setField(key, e.target.value)}
              className="font-mono text-xs"
              autoFocus={editingSecrets[key]}
            />
          ) : (
            <Input
              type="text"
              value={form[key] ?? savedValue}
              readOnly
              className="font-mono text-xs text-white/30"
            />
          )}
          {hasValue && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (editingSecrets[key]) {
                  // Cancel editing — remove from form if user hasn't typed
                  setEditingSecrets((p) => ({ ...p, [key]: false }));
                  const { [key]: _, ...rest } = form;
                  setForm(rest as FormState);
                } else {
                  setEditingSecrets((p) => ({ ...p, [key]: true }));
                }
              }}
            >
              {editingSecrets[key] ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </Button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="relative z-10 space-y-6 max-w-3xl pb-24">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-slate-500/20 to-zinc-500/20 border border-slate-500/10">
          <Settings className="h-5 w-5 text-slate-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="text-xs text-white/30 mt-0.5">
            Bot configuration and connection status
          </p>
        </div>
      </div>

      {/* Backend Status */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-white/25" />
            <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
              Backend Status
            </span>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider ${
              health
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                : "bg-red-500/10 text-red-400 border border-red-500/20"
            }`}
          >
            {health ? (
              <>
                <Wifi className="h-3 w-3" /> Connected
              </>
            ) : (
              <>
                <WifiOff className="h-3 w-3" /> Disconnected
              </>
            )}
          </span>
        </div>
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: "Backend", value: `v${health?.version ?? "—"}` },
            { label: "Frontend", value: `v${frontendVersion}` },
            { label: "Trading Mode", value: currentMode.toUpperCase() },
            { label: "API URL", value: API_BASE_URL },
          ].map((item) => (
            <div
              key={item.label}
              className="rounded-xl bg-white/[0.03] px-3 py-2.5"
            >
              <p className="text-[9px] font-semibold uppercase tracking-wider text-white/20">
                {item.label}
              </p>
              <p className="text-xs font-mono text-white/60 mt-0.5 truncate">
                {item.value}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Trading Mode */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Zap className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Trading Mode
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => handleModeChange("paper")}
            className={`rounded-xl px-4 py-2 text-sm font-bold uppercase tracking-wider transition-all ${
              currentMode === "paper"
                ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                : "bg-white/[0.03] text-white/20 border border-white/[0.06] hover:border-white/10"
            }`}
          >
            <div className="flex items-center gap-2">
              {currentMode === "paper" && (
                <div className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
              )}
              Paper
            </div>
          </button>
          <button
            onClick={() => handleModeChange("live")}
            className={`rounded-xl px-4 py-2 text-sm font-bold uppercase tracking-wider transition-all ${
              currentMode === "live"
                ? "bg-red-500/10 text-red-400 border border-red-500/20"
                : "bg-white/[0.03] text-white/20 border border-white/[0.06] hover:border-white/10"
            }`}
          >
            <div className="flex items-center gap-2">
              {currentMode === "live" && (
                <div className="h-2 w-2 rounded-full bg-red-400 animate-pulse" />
              )}
              Live
            </div>
          </button>
        </div>

        {/* Live mode confirmation modal */}
        {liveConfirmOpen && (
          <div className="mt-4 rounded-xl bg-red-500/5 border border-red-500/20 p-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="h-4 w-4 text-red-400" />
              <span className="text-sm font-semibold text-red-400">
                Enable Live Trading?
              </span>
            </div>
            <p className="text-xs text-white/40 mb-3">
              This will execute real trades on Hyperliquid. Make sure your API
              credentials are configured and you understand the risks.
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setLiveConfirmOpen(false)}
                className="text-white/40"
              >
                Cancel
              </Button>
              <button
                onClick={confirmLiveMode}
                className="rounded-lg bg-red-500/20 border border-red-500/30 px-3 py-1.5 text-xs font-bold text-red-400 hover:bg-red-500/30 transition-colors"
              >
                Yes, enable live trading
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Leverage & Position Sizing */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Zap className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Leverage & Position Sizing
          </span>
        </div>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
                Leverage Multiplier
              </label>
              <Input
                type="number"
                step="1"
                min="1"
                max="100"
                value={val("leverage")}
                onChange={(e) => setField("leverage", parseFloat(e.target.value) || 1)}
                className="font-mono text-xs"
              />
            </div>
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
                Default Trade Size (%)
              </label>
              <Input
                type="number"
                step="1"
                min="1"
                max="100"
                value={val("default_size_pct")}
                onChange={(e) => setField("default_size_pct", parseFloat(e.target.value) || 10)}
                className={`font-mono text-xs ${(form.use_max_size ?? appSettings?.use_max_size ?? false) ? "opacity-30 pointer-events-none" : ""}`}
                disabled={form.use_max_size ?? appSettings?.use_max_size ?? false}
              />
              <p className="text-[10px] text-white/20 mt-1">
                {(form.use_max_size ?? appSettings?.use_max_size ?? false)
                  ? "Trades sized to strategy's max position limit"
                  : "% of strategy equity per trade (overridden by payload size_pct)"}
              </p>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-white/60">Max Size Mode</p>
              <p className="text-[10px] text-white/25 mt-0.5">
                Auto-size each trade to the strategy&apos;s max position limit
              </p>
            </div>
            <button
              onClick={() => {
                const current = form.use_max_size ?? appSettings?.use_max_size ?? false;
                setField("use_max_size", !current);
              }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                (form.use_max_size ?? appSettings?.use_max_size ?? false)
                  ? "bg-[#00ff88]/20 border border-[#00ff88]/30"
                  : "bg-white/[0.06] border border-white/[0.08]"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 rounded-full transition-transform ${
                  (form.use_max_size ?? appSettings?.use_max_size ?? false)
                    ? "translate-x-6 bg-[#00ff88]"
                    : "translate-x-1 bg-white/30"
                }`}
              />
            </button>
          </div>
        </div>
      </div>

      {/* Paper Trading Parameters */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <DollarSign className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Paper Trading
          </span>
        </div>
        <div className="grid grid-cols-2 gap-4">
          {[
            {
              key: "initial_balance" as const,
              label: "Initial Balance ($)",
              step: "100",
              min: "1",
            },
            {
              key: "slippage_pct" as const,
              label: "Slippage (%)",
              step: "0.01",
              min: "0",
              max: "10",
            },
            {
              key: "maker_fee_pct" as const,
              label: "Maker Fee (%)",
              step: "0.001",
              min: "0",
              max: "10",
            },
            {
              key: "taker_fee_pct" as const,
              label: "Taker Fee (%)",
              step: "0.001",
              min: "0",
              max: "10",
            },
          ].map((field) => (
            <div key={field.key}>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
                {field.label}
              </label>
              <Input
                type="number"
                step={field.step}
                min={field.min}
                max={field.max}
                value={val(field.key)}
                onChange={(e) =>
                  setField(field.key, parseFloat(e.target.value) || 0)
                }
                className="font-mono text-xs"
              />
            </div>
          ))}
        </div>
      </div>

      {/* Limit Orders */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Zap className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Limit Orders
          </span>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-white/60">Use Limit Orders</p>
              <p className="text-[10px] text-white/25 mt-0.5">
                Try limit order first (maker fee), fall back to market on timeout
              </p>
            </div>
            <button
              onClick={() => {
                const current = form.use_limit_orders ?? appSettings?.use_limit_orders ?? true;
                setField("use_limit_orders", !current);
              }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                (form.use_limit_orders ?? appSettings?.use_limit_orders ?? true)
                  ? "bg-[#00ff88]/20 border border-[#00ff88]/30"
                  : "bg-white/[0.06] border border-white/[0.08]"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 rounded-full transition-transform ${
                  (form.use_limit_orders ?? appSettings?.use_limit_orders ?? true)
                    ? "translate-x-6 bg-[#00ff88]"
                    : "translate-x-1 bg-white/30"
                }`}
              />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
                Timeout (seconds)
              </label>
              <Input
                type="number"
                step="1"
                min="1"
                max="300"
                value={val("limit_order_timeout_sec")}
                onChange={(e) =>
                  setField("limit_order_timeout_sec", parseFloat(e.target.value) || 30)
                }
                className="font-mono text-xs"
              />
            </div>
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
                Price Offset (%)
              </label>
              <Input
                type="number"
                step="0.01"
                min="0"
                max="5"
                value={val("limit_order_offset_pct")}
                onChange={(e) =>
                  setField("limit_order_offset_pct", parseFloat(e.target.value) || 0)
                }
                className="font-mono text-xs"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Risk Defaults */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Risk Defaults
          </span>
        </div>
        <div className="grid grid-cols-3 gap-4">
          {[
            {
              key: "default_max_position_pct" as const,
              label: "Max Position (%)",
              step: "1",
              min: "1",
              max: "100",
            },
            {
              key: "default_max_drawdown_pct" as const,
              label: "Max Drawdown (%)",
              step: "1",
              min: "1",
              max: "100",
            },
            {
              key: "default_daily_loss_limit" as const,
              label: "Daily Loss Limit ($)",
              step: "10",
              min: "1",
            },
          ].map((field) => (
            <div key={field.key}>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
                {field.label}
              </label>
              <Input
                type="number"
                step={field.step}
                min={field.min}
                max={field.max}
                value={val(field.key)}
                onChange={(e) =>
                  setField(field.key, parseFloat(e.target.value) || 0)
                }
                className="font-mono text-xs"
              />
            </div>
          ))}
        </div>
      </div>

      {/* Hyperliquid API */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Key className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Hyperliquid API
          </span>
        </div>
        <div className="space-y-4">
          {renderSecretField("hl_api_key", "API Key")}
          {renderSecretField("hl_api_secret", "API Secret")}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
              Vault Address
            </label>
            <Input
              type="text"
              placeholder="0x..."
              value={val("hl_vault_address")}
              onChange={(e) => setField("hl_vault_address", e.target.value)}
              className="font-mono text-xs"
            />
          </div>
        </div>
      </div>

      {/* Telegram Notifications */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Bell className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Telegram Notifications
          </span>
        </div>
        <div className="space-y-4">
          {/* Enable toggle */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-white/60">Enable Telegram</p>
              <p className="text-[10px] text-white/25 mt-0.5">
                Send alerts to a Telegram chat when trades open, close, or get blocked
              </p>
            </div>
            <button
              onClick={() => {
                const current = form.telegram_enabled ?? appSettings?.telegram_enabled ?? false;
                setField("telegram_enabled", !current);
              }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                (form.telegram_enabled ?? appSettings?.telegram_enabled ?? false)
                  ? "bg-[#00ff88]/20 border border-[#00ff88]/30"
                  : "bg-white/[0.06] border border-white/[0.08]"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 rounded-full transition-transform ${
                  (form.telegram_enabled ?? appSettings?.telegram_enabled ?? false)
                    ? "translate-x-6 bg-[#00ff88]"
                    : "translate-x-1 bg-white/30"
                }`}
              />
            </button>
          </div>

          {/* Bot Token + Chat ID */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
              Bot Token
            </label>
            <Input
              type="text"
              placeholder="e.g. 123456789:ABCdef..."
              value={form.telegram_bot_token ?? ""}
              onChange={(e) => setField("telegram_bot_token", e.target.value)}
              className="font-mono text-xs"
            />
            {appSettings?.telegram_bot_token && !form.telegram_bot_token && (
              <p className="text-[10px] text-white/20 mt-1">
                Current: {appSettings.telegram_bot_token} — type above to replace
              </p>
            )}
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
              Chat ID
            </label>
            <Input
              type="text"
              placeholder="e.g. 123456789"
              value={form.telegram_chat_id ?? appSettings?.telegram_chat_id ?? ""}
              onChange={(e) => setField("telegram_chat_id", e.target.value)}
              className="font-mono text-xs"
            />
          </div>
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
              Chat ID 2 <span className="text-white/10">(optional)</span>
            </label>
            <Input
              type="text"
              placeholder="e.g. 987654321"
              value={form.telegram_chat_id_2 ?? appSettings?.telegram_chat_id_2 ?? ""}
              onChange={(e) => setField("telegram_chat_id_2", e.target.value)}
              className="font-mono text-xs"
            />
          </div>

          {/* Per-event toggles */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-2 block">
              Notify On
            </label>
            <div className="grid grid-cols-3 gap-3">
              {([
                { key: "notify_trade_open" as const, label: "Trade Open" },
                { key: "notify_trade_close" as const, label: "Trade Close" },
                { key: "notify_risk_breach" as const, label: "Risk Breach" },
              ]).map((item) => (
                <button
                  key={item.key}
                  onClick={() => {
                    const current = form[item.key] ?? appSettings?.[item.key] ?? true;
                    setField(item.key, !current);
                  }}
                  className={`rounded-xl px-3 py-2 text-[11px] font-semibold transition-all ${
                    (form[item.key] ?? appSettings?.[item.key] ?? true)
                      ? "bg-[#00ff88]/10 text-[#00ff88] border border-[#00ff88]/20"
                      : "bg-white/[0.03] text-white/20 border border-white/[0.06] hover:border-white/10"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          {/* Test button */}
          <Button variant="outline" onClick={handleTestTelegram} disabled={sendingTest}>
            <Send className="h-3.5 w-3.5" />
            {sendingTest ? "Sending..." : "Send Test Message"}
          </Button>
        </div>
      </div>

      {/* Webhook Configuration */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Webhook className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Webhook Configuration
          </span>
        </div>
        <div className="space-y-4">
          {renderSecretField("webhook_secret", "Webhook Secret")}

          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
              Webhook URL (use in TradingView alerts)
            </label>
            <div className="flex gap-2">
              <Input
                type="text"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://your-ngrok-url.ngrok-free.app/api/webhook"
                className="font-mono text-xs"
              />
              <Button variant="outline" size="sm" onClick={copyWebhookUrl}>
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
            <p className="text-[10px] text-white/20 mt-1">
              Paste your ngrok public URL here (e.g. https://abc123.ngrok-free.app/api/webhook)
            </p>
          </div>

          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
              TradingView Alert Message Template
            </label>
            <pre className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-4 text-[11px] text-white/30 font-mono overflow-x-auto leading-relaxed">
              {`{
  "secret": "your-webhook-secret",
  "strategy": "My Strategy Name",
  "action": "buy",
  "symbol": "{{ticker}}",
  "size_pct": 10,
  "price": "{{close}}",
  "message": "{{strategy.order.comment}}"
}`}
            </pre>
          </div>

          <Button variant="outline" onClick={testWebhook}>
            <RefreshCw className="h-3.5 w-3.5" /> Send Test Webhook
          </Button>
        </div>
      </div>

      {/* Supported Actions */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center gap-2 mb-4">
          <FileCode2 className="h-4 w-4 text-white/25" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
            Supported Actions
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {[
            { action: "buy", desc: "Close short if open, then open long" },
            { action: "sell", desc: "Close long if open, then open short" },
            { action: "close_long", desc: "Close a long position" },
            { action: "close_short", desc: "Close a short position" },
            { action: "close_all", desc: "Close all positions for strategy" },
          ].map((item) => (
            <div
              key={item.action}
              className="flex items-center gap-3 rounded-xl bg-white/[0.03] border border-white/[0.04] p-3"
            >
              <code className="text-blue-400 text-xs font-mono">
                {item.action}
              </code>
              <span className="text-white/25 text-[11px]">{item.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Save Bar */}
      {isDirty && (
        <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-white/[0.06] bg-[#0a0e1a]/95 backdrop-blur-xl">
          <div className="max-w-3xl mx-auto flex items-center justify-between px-6 py-3">
            <p className="text-xs text-white/40">You have unsaved changes</p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={discardChanges}
                className="text-white/40"
              >
                <X className="h-3.5 w-3.5 mr-1" /> Discard
              </Button>
              <button
                onClick={saveChanges}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#00ff88]/10 border border-[#00ff88]/20 px-4 py-1.5 text-xs font-bold text-[#00ff88] hover:bg-[#00ff88]/20 transition-colors disabled:opacity-50"
              >
                <Save className="h-3.5 w-3.5" />
                {saving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
