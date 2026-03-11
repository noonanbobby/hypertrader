import { cn } from "@/lib/utils";
import { HTMLAttributes } from "react";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "success" | "warning" | "danger";
}

export function Badge({
  className,
  variant = "default",
  ...props
}: BadgeProps) {
  const variants = {
    default: "bg-white/[0.06] text-white/40 border border-white/[0.06]",
    success:
      "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
    warning:
      "bg-amber-500/10 text-amber-400 border border-amber-500/20",
    danger: "bg-red-500/10 text-red-400 border border-red-500/20",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}
