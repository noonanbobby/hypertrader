"use client";

import { cn } from "@/lib/utils";
import { ReactNode } from "react";
import { X } from "lucide-react";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  size?: "md" | "lg" | "xl";
}

export function Dialog({ open, onClose, children, size = "md" }: DialogProps) {
  if (!open) return null;

  const sizes = {
    md: "max-w-lg",
    lg: "max-w-2xl",
    xl: "max-w-4xl",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="fixed inset-0 bg-black/70 backdrop-blur-md"
        onClick={onClose}
      />
      <div
        className={cn(
          "relative z-50 w-full rounded-2xl border border-white/[0.08] bg-[#0c1021]/95 backdrop-blur-xl p-6 shadow-2xl shadow-black/50",
          sizes[size]
        )}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-lg p-1 text-white/20 hover:text-white/50 hover:bg-white/[0.05] transition-all"
        >
          <X className="h-4 w-4" />
        </button>
        {children}
      </div>
    </div>
  );
}

export function DialogHeader({ children }: { children: ReactNode }) {
  return <div className="mb-5 pr-8">{children}</div>;
}

export function DialogTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-lg font-bold text-white">{children}</h2>;
}
