"use client";

interface BadgeProps {
  children: React.ReactNode;
  variant: "long" | "short" | "buy" | "sell" | "success" | "error" | "neutral" | "info";
  size?: "sm" | "md";
  className?: string;
}

const variantStyles: Record<BadgeProps["variant"], { bg: string; text: string }> = {
  long: { bg: "rgba(38,166,154,0.15)", text: "#26a69a" },
  short: { bg: "rgba(239,83,80,0.15)", text: "#ef5350" },
  buy: { bg: "rgba(38,166,154,0.15)", text: "#26a69a" },
  sell: { bg: "rgba(239,83,80,0.15)", text: "#ef5350" },
  success: { bg: "rgba(38,166,154,0.15)", text: "#26a69a" },
  error: { bg: "rgba(239,83,80,0.15)", text: "#ef5350" },
  neutral: { bg: "rgba(120,123,134,0.15)", text: "#787b86" },
  info: { bg: "rgba(41,98,255,0.15)", text: "#2962ff" },
};

export function Badge({ children, variant, size = "sm", className = "" }: BadgeProps) {
  const styles = variantStyles[variant];
  const padding = size === "sm" ? "px-2 py-0.5" : "px-3 py-1";
  const textSize = size === "sm" ? "text-[10px]" : "text-xs";

  return (
    <span
      className={`inline-flex items-center rounded-md font-semibold uppercase tracking-wide ${padding} ${textSize} ${className}`}
      style={{
        backgroundColor: styles.bg,
        color: styles.text,
      }}
    >
      {children}
    </span>
  );
}

interface StatusDotProps {
  status: "ok" | "degraded" | "down" | "unknown";
  label?: string;
  className?: string;
}

const dotColors: Record<StatusDotProps["status"], string> = {
  ok: "#26a69a",
  degraded: "#ff9800",
  down: "#ef5350",
  unknown: "#787b86",
};

export function StatusDot({ status, label, className = "" }: StatusDotProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <span
        className="h-2 w-2 rounded-full"
        style={{ backgroundColor: dotColors[status] }}
        aria-label={`Status: ${status}`}
      />
      {label && (
        <span className="text-xs" style={{ color: "#d1d4dc" }}>
          {label}
        </span>
      )}
    </span>
  );
}
