"use client";

interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
  rounded?: boolean;
}

export function Skeleton({ className = "", width, height, rounded = false }: SkeletonProps) {
  return (
    <div
      className={`shimmer ${rounded ? "rounded-full" : "rounded-lg"} ${className}`}
      style={{
        width: typeof width === "number" ? `${width}px` : width,
        height: typeof height === "number" ? `${height}px` : height,
      }}
      role="status"
      aria-label="Loading"
    />
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-xl border p-4 ${className}`}
      style={{
        backgroundColor: "#1e222d",
        borderColor: "rgba(42,46,57,0.6)",
      }}
    >
      <Skeleton height={12} width="40%" className="mb-3" />
      <Skeleton height={24} width="70%" className="mb-2" />
      <Skeleton height={12} width="55%" />
    </div>
  );
}

export function SkeletonChart({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-xl border ${className}`}
      style={{
        backgroundColor: "#1e222d",
        borderColor: "rgba(42,46,57,0.6)",
      }}
    >
      <div className="flex items-center gap-2 border-b p-3" style={{ borderColor: "rgba(42,46,57,0.5)" }}>
        <Skeleton height={14} width={60} />
        <Skeleton height={14} width={80} />
        <Skeleton height={14} width={60} />
        <Skeleton height={14} width={60} />
      </div>
      <div className="p-4">
        <Skeleton height="100%" width="100%" className="min-h-[200px]" />
      </div>
    </div>
  );
}
