import { FlaskConical, Radio } from "lucide-react";

interface ModeBadgeProps {
  mode: string;
}

export function ModeBadge({ mode }: ModeBadgeProps) {
  if (mode === "live") {
    return (
      <div className="flex items-center gap-2 rounded-full bg-red-500/10 border border-red-500/20 px-3 py-1.5">
        <div className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
        <span className="text-[11px] font-bold text-red-400 uppercase tracking-wider">
          Live Trading
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 rounded-full bg-amber-500/10 border border-amber-500/20 px-3 py-1.5">
      <FlaskConical className="h-3 w-3 text-amber-400" />
      <span className="text-[11px] font-bold text-amber-400 uppercase tracking-wider">
        Paper Mode
      </span>
    </div>
  );
}
