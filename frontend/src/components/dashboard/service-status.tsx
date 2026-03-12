"use client";

import { useSystemStatus } from "@/hooks/use-api";
import { useWebSocket } from "@/hooks/use-websocket";
import type { ServiceCheck } from "@/types";
import {
  Server,
  Globe,
  Radio,
  MessageSquare,
  Copy,
  Check,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { useState, useCallback } from "react";

const SERVICE_ICONS: Record<string, React.ElementType> = {
  backend: Server,
  ngrok: Globe,
  websocket: Radio,
  telegram: MessageSquare,
};

function StatusDot({ status }: { status: ServiceCheck["status"] }) {
  if (status === "ok") {
    return (
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#00ff88] opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-[#00ff88]" />
      </span>
    );
  }
  if (status === "degraded") {
    return <span className="inline-flex h-2 w-2 rounded-full bg-amber-400" />;
  }
  return <span className="inline-flex h-2 w-2 rounded-full bg-[#ff4444]" />;
}

function CopyWebhookButton({ ngrokUrl }: { ngrokUrl: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    const webhookUrl = `${ngrokUrl}/api/webhook`;
    navigator.clipboard.writeText(webhookUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [ngrokUrl]);

  return (
    <button
      onClick={handleCopy}
      className="ml-1 p-0.5 rounded hover:bg-white/10 transition-colors"
      title={`Copy webhook URL: ${ngrokUrl}/api/webhook`}
    >
      {copied ? (
        <Check className="h-3 w-3 text-[#00ff88]" />
      ) : (
        <Copy className="h-3 w-3 text-white/40 hover:text-white/70" />
      )}
    </button>
  );
}

function ServiceIndicator({ service }: { service: ServiceCheck }) {
  const Icon = SERVICE_ICONS[service.name] || Server;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5">
      <Icon className="h-3.5 w-3.5 text-white/40" />
      <StatusDot status={service.status} />
      <span className="text-[11px] font-medium text-white/70 capitalize">
        {service.name}
      </span>
      {service.message && (
        <span className="text-[10px] text-white/30">{service.message}</span>
      )}
      {service.name === "ngrok" && service.status === "ok" && service.url && (
        <CopyWebhookButton ngrokUrl={service.url} />
      )}
    </div>
  );
}

export function ServiceStatus() {
  const { data: status, error, isLoading } = useSystemStatus();
  const { connected: wsConnected } = useWebSocket();

  // Backend unreachable
  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-[#ff4444]/40 bg-[#ff4444]/10 px-4 py-2">
        <AlertTriangle className="h-4 w-4 text-[#ff4444]" />
        <span className="text-xs font-medium text-[#ff4444]">
          Backend unreachable — services cannot be monitored
        </span>
      </div>
    );
  }

  // Loading
  if (isLoading || !status) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-white/5 bg-white/[0.02] px-4 py-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-white/30" />
        <span className="text-[11px] text-white/30">Checking services...</span>
      </div>
    );
  }

  // Override websocket status with frontend-side check (more accurate)
  const wsStatus: ServiceCheck = {
    ...status.websocket,
    status: wsConnected ? "ok" : "down",
    message: wsConnected ? status.websocket.message : "Disconnected",
  };

  const services = [status.backend, status.ngrok, wsStatus, status.telegram];
  const hasDown = services.some((s) => s.status === "down");
  const hasDegraded = services.some((s) => s.status === "degraded");

  const borderColor = hasDown
    ? "border-[#ff4444]/30"
    : hasDegraded
      ? "border-amber-400/30"
      : "border-white/5";

  return (
    <div
      className={`flex items-center justify-between rounded-xl border ${borderColor} bg-white/[0.02] backdrop-blur-xl`}
    >
      <div className="flex items-center divide-x divide-white/5">
        {services.map((service) => (
          <ServiceIndicator key={service.name} service={service} />
        ))}
      </div>
    </div>
  );
}
