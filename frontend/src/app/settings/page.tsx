"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useDashboard } from "@/hooks/use-api";
import { getHealth } from "@/lib/api";
import { API_BASE_URL } from "@/lib/constants";
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
} from "lucide-react";

export default function SettingsPage() {
  const { addToast } = useToast();
  const { data: dashboard } = useDashboard();
  const [health, setHealth] = useState<{
    status: string;
    mode: string;
    version: string;
  } | null>(null);

  const webhookUrl = `${API_BASE_URL}/api/webhook`;

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

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

  return (
    <div className="relative z-10 space-y-6 max-w-3xl">
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

      {/* Connection Status */}
      <div className="gradient-border rounded-2xl backdrop-blur-xl bg-white/[0.02] p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-white/25" />
            <span className="text-xs font-semibold uppercase tracking-wider text-white/25">
              Backend Status
            </span>
          </div>
          <span className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider ${
            health
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
              : "bg-red-500/10 text-red-400 border border-red-500/20"
          }`}>
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
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Version", value: health?.version ?? "—" },
            { label: "Trading Mode", value: (health?.mode ?? "—").toUpperCase() },
            { label: "API URL", value: API_BASE_URL },
          ].map((item) => (
            <div key={item.label} className="rounded-xl bg-white/[0.03] px-3 py-2.5">
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
        <div className="flex items-center gap-4">
          <span className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold uppercase tracking-wider ${
            dashboard?.trading_mode === "paper"
              ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
              : "bg-red-500/10 text-red-400 border border-red-500/20"
          }`}>
            {dashboard?.trading_mode === "paper" && (
              <div className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
            )}
            {dashboard?.trading_mode === "paper"
              ? "Paper Trading"
              : "Live Trading"}
          </span>
          <p className="text-[10px] text-white/20">
            Change mode in backend .env file (TRADING_MODE=paper|live)
          </p>
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
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-white/20 mb-1.5 block">
              Webhook URL (use in TradingView alerts)
            </label>
            <div className="flex gap-2">
              <Input value={webhookUrl} readOnly className="font-mono text-xs" />
              <Button variant="outline" size="sm" onClick={copyWebhookUrl}>
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
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
            { action: "buy", desc: "Close any position, open long" },
            { action: "sell", desc: "Close any position, open short" },
            { action: "close_long", desc: "Close a long position" },
            { action: "close_short", desc: "Close a short position" },
            { action: "close_all", desc: "Close all positions for strategy" },
          ].map((item) => (
            <div
              key={item.action}
              className="flex items-center gap-3 rounded-xl bg-white/[0.03] border border-white/[0.04] p-3"
            >
              <code className="text-blue-400 text-xs font-mono">{item.action}</code>
              <span className="text-white/25 text-[11px]">{item.desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
